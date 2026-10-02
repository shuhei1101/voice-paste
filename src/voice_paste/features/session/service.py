"""セッションの状態の遷移と排他、録音から出力までの流れ。"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from voice_paste.features.session.types import Session, SessionDeps, SessionState
from voice_paste.shared.errors import (
    DeliveryError,
    SessionBusyError,
    SessionNotFoundError,
    TranscriptionError,
)
from voice_paste.shared.types import Entry, Recording, TranscriptionOutcome

logger = logging.getLogger(__name__)

IDLE_DETAIL: str = "idle"
"""待機中に戻ったことを知らせるときの、知らせの理由の文字。"""

WORKER_THREAD_NAME: str = "session-worker"
"""文字起こしから届けるまでを動かすワーカースレッドの名前。"""


class SessionManager:
    """セッションを同時に 1 つだけ持ち、入口からの操作で状態を進める。

    全てのメソッドは Lock の中で状態を確かめて書き換える（API・ホットキー・トレイ・上限のタイマーが別のスレッドから呼ぶ）。
    文字起こしから届けるまでは専用のワーカースレッドで動かし、終わったらセッションを空にして待機中に戻す。
    """

    def __init__(self, deps: SessionDeps, session_limit: timedelta) -> None:
        """配線済みの依存と、API のセッションの上限時間を受ける。"""
        self._deps = deps
        self._session: Session | None = None
        self._lock = threading.Lock()
        self._session_limit = session_limit

    # === 開始・一時停止・再開 ===

    def start(self, entry: Entry | str, callback_url: str | None = None) -> Session:
        """待機中なら新しいセッションを作り、録音を始める。"""
        with self._lock:
            # 1. セッションが残っていれば断る（処理中）
            if self._session is not None:
                logger.info(
                    f"処理中のため開始を断った（入口: {entry}・処理中のセッション: {self._session.id}）"
                )
                raise SessionBusyError("ほかの録音か文字起こしを処理中です")

            # 2. 録音を始める（マイクを開けなければ例外のまま伝え、セッションは作らない）
            self._deps.start_recording()

            # 3. セッションを作り、状態を recording にして知らせる
            session = Session(
                id=str(uuid.uuid4()),
                entry=Entry(entry),
                state=SessionState.RECORDING,
                started_at=self._deps.now(),
                callback_url=callback_url,
                output_id=None,
                output_target=None,
            )
            self._session = session
            logger.info(f"セッションを始めた（{session.id}・入口: {session.entry}）")
            self._deps.notify("state_changed", str(session.state))
            return session

    def pause(self) -> None:
        """ホットキー・トレイの録音を一時停止する（recording → paused）。"""
        with self._lock:
            session = self._session
            # ホットキー・トレイの録音中だけ一時停止する（API のセッションなどは何もしない）
            if session is None or session.entry == Entry.API or session.state != SessionState.RECORDING:
                return
            self._deps.pause_recording()
            self._change_state(session, SessionState.PAUSED)

    def resume(self) -> None:
        """一時停止した録音を再開する（paused → recording）。"""
        with self._lock:
            session = self._session
            # ホットキー・トレイの一時停止中だけ再開する
            if session is None or session.entry == Entry.API or session.state != SessionState.PAUSED:
                return
            self._deps.resume_recording()
            self._change_state(session, SessionState.RECORDING)

    # === 停止・完了・取り消し ===

    def stop(self, session_id: str) -> None:
        """API の録音を止めて完了を待つ（recording → stopped）。"""
        with self._lock:
            session = self._session
            # 今のセッションで、録音中か停止中のときだけ受ける
            if (
                session is None
                or session.id != session_id
                or session.state not in (SessionState.RECORDING, SessionState.STOPPED)
            ):
                raise SessionNotFoundError("止められるセッションがありません")

            # 録音中なら止めて、貯めた音をセッションに持たせる（止めた後の停止は何もしない）
            if session.state == SessionState.RECORDING:
                recording = self._deps.stop_recording()
                self._session = replace(session, state=SessionState.STOPPED, recording=recording)
                self._deps.notify("state_changed", str(SessionState.STOPPED))

    def complete(
        self,
        session_id: str | None = None,
        output_id: str | None = None,
        output_target: str | None = None,
    ) -> None:
        """録音を確定して保存し、文字起こしから届けるまでをワーカースレッドで始める。"""
        with self._lock:
            session = self._session
            if session_id is not None:
                # API: 今のセッションの ID と入口が合い、確定できる状態か
                if (
                    session is None
                    or session.id != session_id
                    or session.entry != Entry.API
                    or session.state not in (SessionState.RECORDING, SessionState.STOPPED)
                ):
                    raise SessionNotFoundError("完了できるセッションがありません")
            elif (
                session is None
                or session.entry == Entry.API
                or session.state not in (SessionState.RECORDING, SessionState.PAUSED)
            ):
                # ホットキー・トレイ: 確定できる録音が無ければ何もしない（API のセッションへの確定のホットキーを含む）
                return

            # 止めていなければ止めてから、録音を保存して transcribing にする（失敗したら片付けて送出し直す）
            try:
                recording = self._stopped_recording(session)
                audio_path = self._deps.save_recording(session.id, recording)
            except Exception as error:
                self._fail_confirm(session, error)
                raise
            confirmed = replace(
                session,
                state=SessionState.TRANSCRIBING,
                output_id=output_id,
                output_target=output_target,
                recording=None,
            )
            self._session = confirmed
            logger.info(
                f"録音を確定した（{session.id}・{recording.duration_sec:.1f} 秒・{audio_path}）"
            )
            self._deps.notify("state_changed", str(confirmed.state))

            # 文字起こしから届けるまではワーカースレッドで動かす
            self._start_worker(self._run_after_confirm, confirmed, audio_path)

    def cancel(self) -> None:
        """ホットキー・トレイの録音を捨てて待機中に戻す。"""
        with self._lock:
            session = self._session
            # ホットキー・トレイの録音中か一時停止中だけ捨てる（API のセッションは何もしない）
            if (
                session is None
                or session.entry == Entry.API
                or session.state not in (SessionState.RECORDING, SessionState.PAUSED)
            ):
                return
            self._deps.discard_recording()
            self._session = None
            logger.info(f"録音を取り消した（{session.id}）")
            self._deps.notify("state_changed", IDLE_DETAIL)

    def close(self) -> None:
        """終了時に、残っているセッションの録音を捨てて待機中に戻す。"""
        with self._lock:
            session = self._session
            # 文字起こし中・届け中はワーカースレッドが終わり次第セッションを空にする
            if session is None or session.state in (
                SessionState.TRANSCRIBING,
                SessionState.DELIVERING,
            ):
                return
            # 止めていない録音だけ捨てる（止めた録音は貯めた音を手放すだけ）
            if session.state != SessionState.STOPPED:
                self._deps.discard_recording()
            self._session = None
            logger.warning(f"終了のため録音を捨てた（{session.id}・入口: {session.entry}）")

    # === 上限での打ち切り ===

    def truncate_if_expired(self) -> bool:
        """API のセッションが開始から上限時間を過ぎていれば打ち切り、打ち切ったかを返す。"""
        with self._lock:
            session = self._session
            # API のセッションが録音中か停止中で、開始から上限時間を過ぎているか
            if (
                session is None
                or session.entry != Entry.API
                or session.state not in (SessionState.RECORDING, SessionState.STOPPED)
            ):
                return False
            elapsed = self._deps.now() - session.started_at
            if elapsed < self._session_limit:
                return False

            # 止めていなければ止めてから、録音を保存して delivering にする
            try:
                recording = self._stopped_recording(session)
                audio_path = self._deps.save_recording(session.id, recording)
            except Exception as error:  # noqa: BLE001 失敗は片付けて知らせ、上限のタイマーが同じ失敗を繰り返さないよう送出しない
                self._fail_confirm(session, error)
                return True
            truncated = replace(session, state=SessionState.DELIVERING, recording=None)
            self._session = truncated
            logger.warning(
                f"完了が来ないまま上限で打ち切った（{session.id}・経過 {elapsed.total_seconds():.0f} 秒）"
            )
            self._deps.notify("state_changed", str(truncated.state))

        # ロックを離してから届ける（返送の再送を待つ間もロックを持たず、その間の開始は断ってすぐ返す）
        self._start_worker(self._deliver_truncated, truncated, audio_path)
        return True

    # === ワーカースレッドの中 ===

    def _run_after_confirm(self, session: Session, audio_path: Path) -> None:
        """文字起こし → 補正 → 履歴への書き足し → 届けるを行い、待機中に戻す。"""
        is_api = session.entry == Entry.API
        # どこで失敗したかを知らせの種類に使う（届ける前か後か）
        stage = "transcription"
        try:
            # 1. 録音を文字に起こす
            try:
                text = self._deps.transcribe(audio_path, None)
            except TranscriptionError as error:
                logger.error(f"文字起こしに失敗した（{session.id}・{error}）")
                self._report_failure(session, str(error), stage)
                return

            # 2〜3. 用語集で補正し、履歴に書き足す
            corrected = self._deps.correct(text)
            self._deps.append_text(audio_path, corrected)

            # 4. 結果が空で入口が api でなければ、届けずに終える
            if not corrected and not is_api:
                logger.info(f"文字起こしの結果が空だった（{session.id}）")
                return

            # 5〜6. 届ける（届けられなければ知らせる）
            self._change_state_by_id(session.id, SessionState.DELIVERING)
            stage = "delivery"
            outcome = TranscriptionOutcome(
                session_id=session.id, result="transcribed", text=corrected, error=None
            )
            try:
                self._deps.deliver(session, outcome)
            except DeliveryError as error:
                logger.error(f"出力先へ届けられなかった（{session.id}・{error}）")
                self._deps.notify("delivery_failed", str(error))
        except Exception as error:  # noqa: BLE001 どの経路でもセッションを空にして待機中へ戻すため
            logger.exception(f"確定後の流れで想定外の例外（{session.id}）")
            self._report_failure(session, str(error), stage)
        finally:
            self._finish(session, audio_path)

    def _announce_failure(self, session: Session, reason: str) -> None:
        """確定できなかったセッションの失敗を知らせ、待機中を知らせる。"""
        try:
            self._report_failure(session, reason, "transcription")
        finally:
            self._deps.notify("state_changed", IDLE_DETAIL)

    def _deliver_truncated(self, session: Session, audio_path: Path) -> None:
        """打ち切りを届け、待機中に戻す。"""
        outcome = TranscriptionOutcome(
            session_id=session.id, result="truncated", text="", error=None
        )
        try:
            self._deps.deliver(session, outcome)
        except Exception:  # noqa: BLE001 届けられなくても待機中へ戻すため
            logger.exception(f"打ち切りを届けられなかった（{session.id}）")
        finally:
            self._finish(session, audio_path)

    def _report_failure(self, session: Session, reason: str, stage: str) -> None:
        """失敗を知らせる。API は呼び出し元へ failed を届け、それ以外は画面・トレイへ知らせる。"""
        # 入口が api か
        if session.entry == Entry.API:
            # api: 呼び出し元へ failed を届ける（届けられなくてもワーカースレッドを落とさない）
            outcome = TranscriptionOutcome(
                session_id=session.id, result="failed", text="", error=reason
            )
            try:
                self._deps.deliver(session, outcome)
            except Exception:  # noqa: BLE001 失敗の返送の失敗でワーカースレッドを落とさないため
                logger.exception(f"失敗を届けられなかった（{session.id}）")
        else:
            # hotkey・tray: 文字起こしの前か後かで知らせの種類を分ける
            event = "transcription_failed" if stage == "transcription" else "delivery_failed"
            self._deps.notify(event, reason)

    def _finish(self, session: Session, audio_path: Path) -> None:
        """一時の音声を消し、セッションを空にして待機中を知らせる。"""
        try:
            self._deps.discard_temporary(audio_path)
        finally:
            with self._lock:
                self._session = None
            self._deps.notify("state_changed", IDLE_DETAIL)
            logger.info(f"セッションを終えた（{session.id}）")

    # === 内部 ===

    def _stopped_recording(self, session: Session) -> Recording:
        """止めた録音を返す。止めていなければ録音を止めて返す。"""
        # 停止中: 止めたときにセッションが持った貯めた音を使う
        if session.state == SessionState.STOPPED and session.recording is not None:
            return session.recording
        return self._deps.stop_recording()

    def _fail_confirm(self, session: Session, error: Exception) -> None:
        """録音の停止か保存に失敗したセッションを片付けて待機中に戻し、失敗の知らせをワーカースレッドで行う。ロックを持って呼ぶ。"""
        # 1. 止めていない録音が残っているかもしれないので捨てる（音量も戻る。既に止まっていれば握る）
        if session.state != SessionState.STOPPED:
            try:
                self._deps.discard_recording()
            except Exception:  # noqa: BLE001 失敗の片付けの中の失敗で元の失敗を隠さないため
                logger.warning(f"録音を捨てられなかった（{session.id}）", exc_info=True)

        # 2. セッションを空にする
        self._session = None
        logger.exception(f"録音を確定できなかった（{session.id}・{error}）")

        # 3. 失敗を知らせ、待機中を知らせる（返送を待つ間もロックを持たないようワーカースレッドで行う）
        self._start_worker(self._announce_failure, session, str(error))

    def _change_state(self, session: Session, state: SessionState) -> None:
        """ロックを持った状態で、セッションの状態を書き換えて知らせる。"""
        self._session = replace(session, state=state)
        self._deps.notify("state_changed", str(state))

    def _change_state_by_id(self, session_id: str, state: SessionState) -> None:
        """今のセッションが session_id なら、状態を書き換えて知らせる。"""
        with self._lock:
            session = self._session
            if session is not None and session.id == session_id:
                self._change_state(session, state)

    def _start_worker(self, target: Callable[..., Any], *args: object) -> None:
        """target をワーカースレッドで始める。"""
        threading.Thread(
            target=target, args=args, name=WORKER_THREAD_NAME, daemon=True
        ).start()
