"""セッションの状態の遷移と排他、録音から出力までの流れ。"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from voice_paste.features.session.types import ContinuousEnd, Session, SessionDeps, SessionState
from voice_paste.shared.errors import (
    DeliveryError,
    SessionBusyError,
    SessionConflictError,
    SessionNotFoundError,
    TranscriptionError,
)
from voice_paste.shared.settings import Preset
from voice_paste.shared.types import Entry, Recording, Segment, TranscriptionOutcome

logger = logging.getLogger(__name__)

IDLE_DETAIL: str = "idle"
"""待機中に戻ったことを知らせるときの、知らせの理由の文字。"""

WORKER_THREAD_NAME: str = "session-worker"
"""文字起こしから届けるまでを動かすワーカースレッドの名前。"""

type SegmentQueue = queue.Queue[tuple[int, Segment] | ContinuousEnd | None]
"""連続録音の区間（通し番号つき）を区切った順に、ワーカースレッドへ渡す待ち行列。ContinuousEnd は終わりのマーカー、None は終了で返さずにやめるマーカー。"""


class SessionManager:
    """セッションを同時に 1 つだけ持ち、入口からの操作で状態を進める。

    全てのメソッドは Lock の中で状態を確かめて書き換える（API・ホットキー・トレイ・上限のタイマー・録音の区切りのスレッドが別のスレッドから呼ぶ）。
    文字起こしから届けるまでは専用のワーカースレッドで動かし、終わったらセッションを空にして待機中に戻す。
    API の連続録音では、開始でワーカースレッドを 1 つ立て、録音が区切った区間を待ち行列経由で区切った順に起こして返す（録音は続ける）。
    完了か上限で録音を止め、最後の区間の後ろに終わりを返してから待機中に戻す。
    """

    def __init__(
        self, deps: SessionDeps, session_limit: timedelta, continuous_session_limit: timedelta
    ) -> None:
        """配線済みの依存と、API のセッションの上限時間・連続録音のセッションの上限時間を受ける。"""
        self._deps = deps
        self._session: Session | None = None
        self._lock = threading.Lock()
        self._session_limit = session_limit
        self._continuous_session_limit = continuous_session_limit
        # 連続録音の区間をワーカースレッドへ渡す待ち行列。連続録音でなければ None
        self._segments: SegmentQueue | None = None

    def current(self) -> Session | None:
        """今のセッションを返す（待機中は None）。画面が state_changed を受けたときに入口と状態を引く。"""
        with self._lock:
            return self._session

    # === 開始・一時停止・再開 ===

    def start(
        self,
        entry: Entry | str,
        callback_url: str | None = None,
        continuous: bool = False,
        glossary_preset: str | None = None,
    ) -> Session:
        """待機中なら新しいセッションを作り、録音（continuous なら連続録音）を始める。"""
        with self._lock:
            # 1. セッションが残っていれば断る（処理中）
            if self._session is not None:
                logger.info(
                    f"処理中のため開始を断った（入口: {entry}・処理中のセッション: {self._session.id}）"
                )
                raise SessionBusyError("ほかの録音か文字起こしを処理中です")

            # 2. 録音を始める（マイクを開けなければ例外のまま伝え、セッションは作らない）
            segments: SegmentQueue | None = None
            if continuous:
                # 連続録音: 区間の待ち行列を作り、区切った区間と失敗の渡し先を録音に渡す
                segments = queue.Queue()
                self._deps.start_continuous_recording(self._on_segment, self._on_continuous_failed)
                self._segments = segments
            else:
                self._deps.start_recording()

            # 3. セッションを作り、状態を recording にして知らせる
            session = Session(
                id=str(uuid.uuid4()),
                entry=Entry(entry),
                state=SessionState.RECORDING,
                started_at=self._deps.now(),
                callback_url=callback_url,
                output_id=None,
                output_preset=None,
                continuous=continuous,
                glossary_preset=glossary_preset,
            )
            self._session = session
            logger.info(
                f"セッションを始めた（{session.id}・入口: {session.entry}・連続録音: {continuous}）"
            )

            # 連続録音: 区間を起こして返すワーカースレッドを始める
            if segments is not None:
                self._start_worker(self._run_segments, session, segments)
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

            # 連続録音は止めずに断る（完了で終える）
            if session.continuous:
                raise SessionConflictError("連続録音は止められません。完了で終えてください")

            # 録音中なら止めて、貯めた音をセッションに持たせる（止めた後の停止は何もしない）
            if session.state == SessionState.RECORDING:
                recording = self._deps.stop_recording()
                self._session = replace(session, state=SessionState.STOPPED, recording=recording)
                self._deps.notify("state_changed", str(SessionState.STOPPED))

    def complete(
        self,
        session_id: str | None = None,
        output_id: str | None = None,
        preset: Preset | None = None,
    ) -> None:
        """録音を確定して保存し、文字起こしから届けるまでをワーカースレッドで始める。連続録音は録音を止めて終わりまで返す。"""
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

            # 連続録音以外は、止めていなければ止めてから録音を保存して transcribing にする
            if not session.continuous:
                self._confirm(session, output_id, preset)
                return

        # 連続録音は、ロックを離してから録音を止めて終える（止めるときに最後の区間が _on_segment を呼ぶため）
        if not self._finish_continuous_recording(session.id, "completed"):
            raise SessionNotFoundError("完了できるセッションがありません")

    def _confirm(self, session: Session, output_id: str | None, preset: Preset | None) -> None:
        """ロックを持って、録音を止めて保存し（失敗したら片付けて送出し直す）、transcribing にして文字起こしから届けるまでを始める。"""
        try:
            recording = self._stopped_recording(session)
            audio_path = self._deps.save_recording(session.id, recording, None)
        except Exception as error:
            self._fail_confirm(session, error)
            raise
        confirmed = replace(
            session,
            state=SessionState.TRANSCRIBING,
            output_id=output_id,
            output_preset=preset,
            recording=None,
        )
        self._session = confirmed
        logger.info(
            f"録音を確定した（{session.id}・{recording.duration_sec:.1f} 秒・{audio_path}）"
        )
        self._deps.notify("state_changed", str(confirmed.state))

        # 文字起こしから届けるまではワーカースレッドで動かす
        self._start_worker(self._run_after_confirm, confirmed, audio_path)

    def switch_output(self, output_id: str) -> None:
        """固定の出力先で確定したホットキー・トレイの録音の文字起こし中に、届ける出力先を差し替える。"""
        with self._lock:
            session = self._session
            # 文字起こし中の、固定の出力先で確定したホットキー・トレイのセッションだけ差し替える（届け始めた後・API・カスタムプリセットは何もしない）
            if (
                session is None
                or session.entry == Entry.API
                or session.state != SessionState.TRANSCRIBING
                or session.output_preset is not None
            ):
                return
            # 今の出力先と同じなら何もしない
            if output_id == session.output_id:
                return
            self._session = replace(session, output_id=output_id)
            logger.info(f"出力先を切り替えた（{session.id}・{session.output_id} → {output_id}）")
            self._deps.notify("output_changed", output_id)

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
            self._session = None
            logger.warning(f"終了のため録音を捨てた（{session.id}・入口: {session.entry}）")

            if session.continuous:
                # 連続録音: ワーカースレッドは残りの区間と終わりを返さずに終える
                if self._segments is not None:
                    self._segments.put(None)
                    self._segments = None
            elif session.state != SessionState.STOPPED:
                # 止めていない録音だけ捨てる（止めた録音は貯めた音を手放すだけ）
                self._deps.discard_recording()

        # 連続録音の録音は、区切りのスレッドの終わりを待つため、ロックを離してから捨てる（離した後に届いた区間は _on_segment が捨てる）
        if session.continuous:
            self._deps.discard_recording()

    # === 上限での打ち切り ===

    def truncate_if_expired(self) -> bool:
        """API のセッションが開始から上限時間（連続録音は連続録音の上限時間）を過ぎていれば打ち切り、打ち切ったかを返す。"""
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
            limit = self._continuous_session_limit if session.continuous else self._session_limit
            if elapsed < limit:
                return False
            logger.warning(
                f"完了が来ないまま上限で打ち切った（{session.id}・経過 {elapsed.total_seconds():.0f} 秒）"
            )

            # 連続録音は、ロックを離してから録音を止めて残りを返し、終わりに truncated を返す
            if session.continuous:
                continuous_id = session.id
            else:
                continuous_id = None
                # 止めていなければ止めてから、録音を保存して delivering にする
                try:
                    recording = self._stopped_recording(session)
                    audio_path = self._deps.save_recording(session.id, recording, None)
                except Exception as error:  # noqa: BLE001 失敗は片付けて知らせ、上限のタイマーが同じ失敗を繰り返さないよう送出しない
                    self._fail_confirm(session, error)
                    return True
                truncated = replace(session, state=SessionState.DELIVERING, recording=None)
                self._session = truncated
                self._deps.notify("state_changed", str(truncated.state))

        if continuous_id is not None:
            self._finish_continuous_recording(continuous_id, "truncated")
            return True

        # ロックを離してから届ける（返送の再送を待つ間もロックを持たず、その間の開始は断ってすぐ返す）
        self._start_worker(self._deliver_truncated, truncated, audio_path)
        return True

    # === ワーカースレッドの中 ===

    def _run_after_confirm(self, session: Session, audio_path: Path) -> None:
        """文字起こし → 補正 → 履歴への追記 → 届けるを行い、待機中に戻す。"""
        is_api = session.entry == Entry.API
        # どこで失敗したかを知らせの種類に使う（届ける前か後か）
        stage = "transcription"
        try:
            # 1. 録音を文字に起こす
            try:
                # API の録音は画面を出さないので、進みを知らせる関数を渡さない
                on_progress = None if is_api else self._deps.report_progress
                text = self._deps.transcribe(audio_path, on_progress)
            except TranscriptionError as error:
                logger.error(f"文字起こしに失敗した（{session.id}・{error}）")
                self._report_failure(session, str(error), stage)
                return

            # 2〜3. 用語集で補正し、履歴に追記する
            corrected = self._deps.correct(text, session.glossary_preset)
            self._deps.append_text(audio_path, corrected)

            # 4. 結果が空で入口が api でなければ、届けずに終える
            if not corrected and not is_api:
                logger.info(f"文字起こしの結果が空だった（{session.id}）")
                return

            # 5〜6. 届ける（届けられなければ知らせる）。届け始めた後の出力先の切り替えは受けないので、delivering にしたときのセッションで届ける
            delivering = self._start_delivering(session)
            stage = "delivery"
            outcome = TranscriptionOutcome(
                session_id=session.id, result="transcribed", text=corrected, error=None
            )
            try:
                self._deps.deliver(delivering, outcome)
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
        """一時の音声を削除し、セッションを空にして待機中を知らせる。"""
        try:
            self._deps.discard_temporary(audio_path)
        finally:
            with self._lock:
                self._session = None
            self._deps.notify("state_changed", IDLE_DETAIL)
            logger.info(f"セッションを終えた（{session.id}）")

    # === 連続録音 ===

    def _finish_continuous_recording(
        self, session_id: str, result: Literal["completed", "truncated"]
    ) -> bool:
        """連続録音を transcribing にしてからロックを離して録音を止め、最後の区間の後ろに終わりのマーカーを積む。終えられたかを返す。

        録音を止めると区切りのスレッドが最後の区間を _on_segment へ渡す（_on_segment はロックを取る）ため、
        状態を書き換えた後にロックを離してから止める。先に transcribing にするので、同じセッションへの 2 度目の完了・打ち切りは通らない。
        ロックを持たずに呼ぶ。
        """
        # 1. 今のセッションが録音中の連続録音であることを確かめ、transcribing にして知らせる
        with self._lock:
            session = self._session
            segments = self._segments
            if (
                session is None
                or session.id != session_id
                or not session.continuous
                or session.state != SessionState.RECORDING
                or segments is None
            ):
                return False
            self._change_state(session, SessionState.TRANSCRIBING)

        # 2. ロックを離して連続録音を止める（戻るまでに最後の区間が _on_segment へ渡る）。止められなくても、そこまでの区間と終わりは返す
        try:
            self._deps.stop_continuous_recording()
        except Exception:  # noqa: BLE001 止められなくても区切った区間と終わりは返すため
            logger.exception(f"連続録音を止められなかった（{session_id}）")

        # 3. 最後の区間の後ろに終わりのマーカーを積む
        segments.put(ContinuousEnd(result=result))
        logger.info(f"連続録音を終えた（{session_id}・{result}）")
        return True

    def _on_segment(self, segment: Segment) -> None:
        """録音が区切った区間に通し番号を付け、区間の待ち行列へ積む（録音の区切りのスレッドから呼ばれる）。"""
        with self._lock:
            session = self._session
            segments = self._segments
            # 連続録音で、録音中か完了・上限で止めている最中だけ受ける（終了で捨てた後などは区間を捨てる）
            if (
                session is None
                or not session.continuous
                or session.state not in (SessionState.RECORDING, SessionState.TRANSCRIBING)
                or segments is None
            ):
                logger.warning("連続録音でないため区間を捨てた")
                return

            number = session.segment_count + 1
            self._session = replace(session, segment_count=number)
            segments.put((number, segment))
            logger.info(
                f"区間を受けた（{session.id}・{number}・{segment.recording.duration_sec:.1f} 秒・{segment.reason}）"
            )

    def _on_continuous_failed(self, reason: str) -> None:
        """区切りに失敗して録音が止まった連続録音を、それまでの区間の後ろに failed の終わりを返して終える（録音の区切りのスレッドから呼ばれる）。"""
        with self._lock:
            session = self._session
            segments = self._segments
            # 完了・上限・終了で既に終えていれば何もしない
            if (
                session is None
                or not session.continuous
                or session.state != SessionState.RECORDING
                or segments is None
            ):
                return

            # 録音は録音が止めている。終わりのマーカーを積めば、ワーカースレッドがそれまでの区間の後ろに終わりを返す
            self._change_state(session, SessionState.TRANSCRIBING)
            segments.put(ContinuousEnd(result="failed", error=reason))
            logger.error(f"連続録音が区切りの失敗で止まった（{session.id}・{reason}）")

    def _run_segments(self, session: Session, segments: SegmentQueue) -> None:
        """ワーカースレッドで、区間の待ち行列を区切った順に 1 つずつ処理し、終わりのマーカーで終わりを返して待機中に戻す。

        前の区間の返送（再送を含む）を終えてから次の区間を処理するので、返送は通し番号の順に届き、終わりは全ての区間の後ろになる。
        """
        # 処理した区間の数（通し番号は 1 から 1 ずつ増えるので、終わりのマーカーのときは区切った区間の数になる）
        segment_count = 0
        while True:
            item = segments.get()

            # 終了で捨てた: 残りの区間も終わりも返さずに終える（セッションは close が空にしている）
            if item is None:
                return

            # 終わりのマーカー: 終わった理由と区間の数を届けて、ループを抜ける
            if isinstance(item, ContinuousEnd):
                self._deliver_continuous_end(session, item, segment_count)
                break

            number, segment = item
            segment_count = number
            self._process_segment(session, number, segment)

        # セッションを空にして待機中を知らせる
        with self._lock:
            self._session = None
            self._segments = None
        self._deps.notify("state_changed", IDLE_DETAIL)
        logger.info(f"セッションを終えた（{session.id}）")

    def _deliver_continuous_end(
        self, session: Session, end: ContinuousEnd, segment_count: int
    ) -> None:
        """連続録音の終わり（終わった理由と区間の数）を届ける。届けられなくてもログに書いて続ける。"""
        outcome = TranscriptionOutcome(
            session_id=session.id,
            result=end.result,
            text="",
            error=end.error,
            segment_count=segment_count,
        )
        try:
            self._deps.deliver(session, outcome)
        except Exception:  # noqa: BLE001 終わりを届けられなくても待機中へ戻すため
            logger.exception(f"連続録音の終わりを届けられなかった（{session.id}）")

    def _process_segment(self, session: Session, number: int, segment: Segment) -> None:
        """1 区間を保存 → 文字起こし → 補正 → 履歴への追記 → 返すの順に処理する。失敗はその区間の failed として返し、連続録音は止めない。"""
        audio_path: Path | None = None
        try:
            # 1〜3. 区間の音を保存し、文字に起こして用語集で補正し、区間の録音と同じ履歴に追記する
            try:
                audio_path = self._deps.save_recording(session.id, segment.recording, number)
                text = self._deps.transcribe(audio_path, None)
                corrected = self._deps.correct(text, session.glossary_preset)
                self._deps.append_text(audio_path, corrected)
                outcome = TranscriptionOutcome(
                    session_id=session.id,
                    result="transcribed",
                    text=corrected,
                    error=None,
                    segment_number=number,
                )
            except Exception as error:  # noqa: BLE001 どの失敗もこの区間の failed として返し、次の区間へ進むため
                logger.exception(f"区間の文字起こしに失敗した（{session.id}・{number}）")
                outcome = TranscriptionOutcome(
                    session_id=session.id,
                    result="failed",
                    text="",
                    error=str(error),
                    segment_number=number,
                )

            # 4. 届ける（結果が空でも届ける。届けられなければログに書いて次の区間へ進む）
            try:
                self._deps.deliver(session, outcome)
            except Exception:  # noqa: BLE001 区間を届けられなくても次の区間へ進むため
                logger.exception(f"区間を届けられなかった（{session.id}・{number}）")
        finally:
            # 5. どの経路でも、保存した区間が一時の音声なら削除する
            if audio_path is not None:
                self._deps.discard_temporary(audio_path)

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

    def _change_state(self, session: Session, state: SessionState) -> Session:
        """ロックを持った状態で、セッションの状態を書き換えて知らせ、書き換えたセッションを返す。"""
        changed = replace(session, state=state)
        self._session = changed
        self._deps.notify("state_changed", str(state))
        return changed

    def _start_delivering(self, session: Session) -> Session:
        """ロックの中で、今のセッションが session なら状態を delivering にして知らせ、そのときの今のセッションを返す。

        文字起こし中に switch_output で差し替えた出力先は、ここで引き直すセッションが持つ。
        今のセッションが session でなければ（終了で空になったなど）session をそのまま返す。
        """
        with self._lock:
            current = self._session
            if current is None or current.id != session.id:
                return session
            return self._change_state(current, SessionState.DELIVERING)

    def _start_worker(self, target: Callable[..., Any], *args: object) -> None:
        """target をワーカースレッドで始める。"""
        threading.Thread(
            target=target, args=args, name=WORKER_THREAD_NAME, daemon=True
        ).start()
