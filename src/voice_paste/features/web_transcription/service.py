"""ブラウザの音声のジョブの一覧とワーカースレッド、音声の受け付け。"""

from __future__ import annotations

import logging
import queue
import secrets
import shutil
import threading
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from voice_paste.features.web_transcription.types import (
    JobState,
    WebApiDeps,
    WebJob,
    WebTranscriptionDeps,
)
from voice_paste.shared.errors import (
    AudioUnreadableError,
    GlossaryPresetNotFoundError,
    TranscriptionError,
    WebJobNotFoundError,
    WebQueueFullError,
)
from voice_paste.shared.types import AudioProbe

logger = logging.getLogger(__name__)

WEB_QUEUE_LIMIT: int = 10
"""終わっていないジョブ（queued・running）の上限。非機能要件のブラウザの音声の待ちの上限。"""

WEB_FINISHED_JOBS_KEPT: int = 100
"""終わったジョブ（done・failed）をメモリに持つ件数。非機能要件の終わったジョブを持つ件数。"""

JOB_ID_BYTES: int = 16
"""secrets.token_urlsafe に渡す乱数のバイト数（128 bit、22 文字）。"""

WORKER_THREAD_NAME: str = "web-transcription-worker"
"""ブラウザの音声を起こすワーカースレッドの名前。"""

UNEXPECTED_ERROR_MESSAGE: str = "想定していない問題"
"""想定していない例外でジョブを failed にするときの error。例外の中身は載せない。"""

STORE_FAILED_MESSAGE: str = "音声を保存できませんでした"
"""音声を履歴へ移せずにジョブを failed にするときの error。置き場所は載せない。"""


class WebJobQueue:
    """ジョブの一覧と待ち行列を持ち、ワーカースレッドで 1 件ずつ起こす。

    ジョブの一覧は Lock の中で読み書きする（route は uvicorn のスレッド、起こすのはワーカースレッド）。
    終わったジョブは終わった順に控え、終わったジョブを持つ件数を超えたら古い順に一覧から捨てる。
    """

    def __init__(
        self,
        deps: WebTranscriptionDeps,
        *,
        max_pending: int = WEB_QUEUE_LIMIT,
        max_finished: int = WEB_FINISHED_JOBS_KEPT,
    ) -> None:
        """呼ぶ関数と、終わっていないジョブの上限・終わったジョブを持つ件数を受ける。"""
        self._deps = deps
        self._max_pending = max_pending
        self._max_finished = max_finished
        self._jobs: dict[str, WebJob] = {}
        self._finished: deque[str] = deque()
        self._pending: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self, tmp_dir: Path) -> None:
        """一時のフォルダに取り残された音声を削除し、ワーカースレッドを立てる。"""
        # 1. 前の起動で取り残された音声を削除する（削除できないものは残す）
        if tmp_dir.exists():
            for leftover in tmp_dir.iterdir():
                try:
                    leftover.unlink()
                except OSError as error:
                    logger.warning(f"取り残された音声を削除できなかった（{leftover}・{error}）")

        # 2. 受けた音声を書くフォルダを作る
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 3. ワーカースレッドを立てる（終了を待たないデーモン）
        self._thread = threading.Thread(target=self._run, name=WORKER_THREAD_NAME, daemon=True)
        self._thread.start()

    def submit(
        self, job_id: str, audio_path: Path, audio: AudioProbe, glossary_preset: str | None
    ) -> WebJob:
        """終わっていないジョブが上限未満なら、用語集のプリセットの名前（None は指定なし）を持たせたジョブを queued で積んで返す。"""
        with self._lock:
            # 終わっていないジョブが上限に達していれば断る
            pending_count = sum(
                1 for job in self._jobs.values() if job.state in (JobState.QUEUED, JobState.RUNNING)
            )
            if pending_count >= self._max_pending:
                raise WebQueueFullError(f"終わっていないジョブが上限（{self._max_pending} 件）に達している")

            job = WebJob(
                id=job_id,
                state=JobState.QUEUED,
                audio_path=audio_path,
                audio=audio,
                glossary_preset=glossary_preset,
            )
            self._jobs[job_id] = job
            self._pending.put(job_id)
        logger.info(
            f"音声を受け付けた（{job_id}・{audio.size_bytes} バイト・{audio.container}・"
            f"{_format_duration(audio.duration_sec)}・用語集のプリセット: "
            f"{glossary_preset or '設定に従う'}）"
        )
        return job

    def get(self, job_id: str) -> WebJob:
        """ジョブの今の状態を返す。無ければ WebJobNotFoundError を送出する。"""
        with self._lock:
            job = self._jobs.get(job_id)
        # 受け付けていないか、件数を超えて捨てた
        if job is None:
            raise WebJobNotFoundError("そのジョブはありません")
        return job

    def close(self) -> None:
        """待ち行列に止める合図を積み、待ちのジョブの一時のファイルを削除する。起こしている 1 件は待たない。"""
        # 1. 待ち行列に残った ID を取り出し、そのジョブの一時のファイルを削除する
        discarded = 0
        while True:
            try:
                job_id = self._pending.get_nowait()
            except queue.Empty:
                break
            # 止める合図は削除する音声を持たない
            if job_id is None:
                continue
            self._deps.discard_temporary(self.get(job_id).audio_path)
            discarded += 1

        # 2. ワーカースレッドへ止める合図を積む（スレッドはデーモンなので join しない）
        self._pending.put(None)
        logger.info(f"ブラウザの音声のキューを閉じた（捨てた待ちの数: {discarded}）")

    def _run(self) -> None:
        """待ち行列から ID を 1 つずつ取り出して起こす。止める合図を取り出したら終わる。"""
        while True:
            job_id = self._pending.get()
            if job_id is None:
                return
            self._process(job_id)

    def _update(self, job_id: str, **changes: object) -> WebJob:
        """ジョブの項目を差し替えて、差し替えた後のジョブを返す。"""
        with self._lock:
            job = replace(self._jobs[job_id], **changes)  # type: ignore[arg-type] 項目名は呼び出し側が決める
            self._jobs[job_id] = job
        return job

    def _process(self, job_id: str) -> None:
        """1 件を running にして、履歴へ移し、起こして補正し、done か failed で終える。"""
        deps = self._deps
        self._update(job_id, state=JobState.RUNNING)

        def report_progress(segment_end: float, duration: float) -> None:
            """起こし終えた区間の終わりの時刻から、進み具合を書く。"""
            if duration > 0:
                self._update(job_id, progress=min(segment_end / duration, 1.0))

        try:
            # 1. 受けた音声を保存する（履歴を残す設定なら履歴へ移り、audio_path が差し替わる）
            audio_path = deps.store_audio(job_id, self.get(job_id).audio_path)
            self._update(job_id, audio_path=audio_path)

            # 2. 起こして、ジョブの用語集のプリセット（None は設定で選んでいるプリセット）で補正し、履歴に追記する
            text = deps.correct(
                deps.transcribe(audio_path, report_progress), self.get(job_id).glossary_preset
            )
            deps.append_text(audio_path, text)

            # 3. 起こし終えた
            self._update(job_id, state=JobState.DONE, progress=1.0, text=text)
            logger.info(
                f"起こし終えた（{job_id}・{_format_duration(self.get(job_id).audio.duration_sec)}・"
                f"{len(text)} 文字）"
            )
        except TranscriptionError as error:
            self._fail(job_id, str(error), str(error))
        except OSError as error:
            self._fail(job_id, STORE_FAILED_MESSAGE, str(error))
        except Exception:  # noqa: BLE001 ワーカースレッドを止めない。中身は error に載せずログに書く
            logger.exception(f"想定していない例外（{job_id}）")
            self._update(job_id, state=JobState.FAILED, error=UNEXPECTED_ERROR_MESSAGE)

        # 4. 一時のファイルなら削除し（失敗しても通る）、終わったジョブの一覧に追加する
        deps.discard_temporary(self.get(job_id).audio_path)
        self._record_finished(job_id)

    def _fail(self, job_id: str, error: str, reason: str) -> None:
        """ジョブを failed・error で終える。reason はログに書く。"""
        logger.error(f"文字起こしに失敗した（{job_id}・{reason}）")
        self._update(job_id, state=JobState.FAILED, error=error)

    def _record_finished(self, job_id: str) -> None:
        """終わったジョブの一覧に追加し、件数を超えたらいちばん古い件を一覧から捨てる。"""
        with self._lock:
            self._finished.append(job_id)
            while len(self._finished) > self._max_finished:
                self._jobs.pop(self._finished.popleft(), None)


def _format_duration(duration_sec: float | None) -> str:
    """ログに書く秒数の文字にする。求まらなければ「秒数不明」を返す。"""
    if duration_sec is None:
        return "秒数不明"
    return f"{duration_sec:.1f} 秒"


def accept_audio(
    file: BinaryIO, *, deps: WebApiDeps, glossary_preset: str | None = None
) -> WebJob:
    """指定された用語集のプリセットと受けた音声の形式を確かめ、一時のファイルへ書いてジョブを積む。"""
    # 1. 空文字は指定なしとして扱う
    if glossary_preset == "":
        glossary_preset = None

    # 2. 指定された名前が今の設定の一覧に無ければ、音声を読まずに断る
    if glossary_preset is not None and not deps.glossary_preset_exists(glossary_preset):
        logger.warning(f"用語集のプリセットが無いため断った（{glossary_preset}）")
        raise GlossaryPresetNotFoundError(f"用語集のプリセットが無い（{glossary_preset}）")

    # 3. 音声の形式を読む（読めなければ AudioUnreadableError が伝わる）
    try:
        audio = deps.probe_audio(file)
    except AudioUnreadableError as error:
        logger.warning(f"読めない音声を断った（{error}）")
        raise

    # 4. ID を作り、容れ物の拡張子の一時のファイルへ頭から写す
    job_id = secrets.token_urlsafe(JOB_ID_BYTES)
    audio_path = deps.tmp_dir / f"{job_id}{audio.suffix}"
    file.seek(0)
    try:
        with audio_path.open("wb") as destination:
            shutil.copyfileobj(file, destination)
    except OSError:
        # 書きかけのファイルを残さない
        audio_path.unlink(missing_ok=True)
        raise

    # 5. 用語集のプリセットの名前と共にキューに積む（上限ならコピーした一時のファイルを削除してそのまま送出する）
    try:
        return deps.queue.submit(job_id, audio_path, audio, glossary_preset)
    except WebQueueFullError as error:
        audio_path.unlink(missing_ok=True)
        logger.warning(f"待ちが上限のため断った（{error}）")
        raise
