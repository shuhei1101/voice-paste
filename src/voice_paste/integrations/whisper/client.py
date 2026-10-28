"""文字起こしワーカーの子プロセスの窓口。録音を標準入出力の JSON Lines で渡し、落ちたら 1 回だけ立て直してやり直す。"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

from pydantic import ValidationError

from voice_paste.integrations.whisper.protocol import WorkerMessage
from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import LocalWhisperSettings
from voice_paste.shared.types import ProgressFn

logger = logging.getLogger(__name__)

WORKER_MODULE: str = "voice_paste.integrations.whisper.worker"
"""子プロセスで動かすモジュール（`python -m` で起動する）。"""

CUDA_DLL_PACKAGES: tuple[str, ...] = ("cublas", "cudnn", "cuda_nvrtc")
"""CUDA の DLL を持つ nvidia-* パッケージ（venv の `Lib/site-packages/nvidia/{名前}/bin`）。"""

CREATE_NO_WINDOW: int = 0x08000000
"""Windows でコンソールを出さずに子プロセスを起動するフラグ（subprocess.CREATE_NO_WINDOW）。"""

WORKER_ENCODING: str = "utf-8"
"""子プロセスとの標準入出力の文字コード。"""


class _WorkerExitedError(Exception):
    """子プロセスが応答の途中で終わった（送信できない・標準出力が閉じた）。"""


class WhisperWorkerClient:
    """文字起こしワーカーの子プロセスを持ち、録音を渡して区間ごとの文字を受け取る。"""

    def __init__(
        self,
        *,
        settings: LocalWhisperSettings,
        ready_timeout_sec: float,
        log_dir: Path,
        stop_timeout_sec: float,
        creationflags: int = 0,
    ) -> None:
        """設定・立て直しで ready を待つ上限・ワーカーのログの置き場所・終わりを待つ時間・子プロセスの起動のフラグを受ける。"""
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[WorkerMessage | None] = queue.Queue()
        self._settings = settings
        self._ready_timeout_sec = ready_timeout_sec
        self._log_dir = log_dir
        self._stop_timeout_sec = stop_timeout_sec
        self._creationflags = creationflags
        # stop で止めている最中か。立っている間は子プロセスが終わっても立て直さない（start で下ろす）
        self._stopping = False
        # 立て直しの中から start を呼ぶため、再入できるロックにする
        self._lock = threading.RLock()

    # === 起動 ===

    def start(self, *, ready_timeout_sec: float | None = None) -> None:
        """子プロセスを起動し、ready を待つ。None（起動時の 1 回目）は待つ上限をかけない。"""
        with self._lock:
            self._stopping = False
            started = time.perf_counter()
            process = subprocess.Popen(  # noqa: S603 引数は固定で、シェルを通さない
                [sys.executable, "-u", "-m", WORKER_MODULE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._build_environment(),
                text=True,
                encoding=WORKER_ENCODING,
                bufsize=1,
                creationflags=self._creationflags,
            )
            self._process = process
            self._messages = queue.Queue()
            # 標準出力は 1 行ずつキューへ、標準エラーはロガーへ流す
            threading.Thread(
                target=self._pump_stdout, args=(process, self._messages), daemon=True
            ).start()
            threading.Thread(target=self._forward_stderr, args=(process,), daemon=True).start()

            try:
                self._send(
                    "config",
                    model=self._settings.model,
                    device=self._settings.device,
                    compute_type=self._settings.compute_type,
                    cpu_threads=self._settings.cpu_threads,
                    num_workers=self._settings.num_workers,
                    log_dir=str(self._log_dir),
                )
                self._wait_ready(ready_timeout_sec)
            except _WorkerExitedError:
                # config を送信する前に子プロセスが終わっていた
                self._halt()
                raise EngineError("文字起こしワーカーが起動の直後に終わった") from None
            except EngineError:
                # ready が届かない: 子プロセスを止めてから知らせる
                self._halt()
                raise
            logger.info(
                f"文字起こしワーカーが立ち上がった（pid {process.pid}・"
                f"{time.perf_counter() - started:.1f} 秒）"
            )

    def _build_environment(self) -> dict[str, str]:
        """子プロセスの環境を作る（CUDA の DLL の場所を PATH の先頭へ追加する）。"""
        environment = os.environ.copy()
        nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        dll_dirs = [
            str(nvidia_root / name / "bin")
            for name in CUDA_DLL_PACKAGES
            if (nvidia_root / name / "bin").is_dir()
        ]
        environment["PATH"] = os.pathsep.join([*dll_dirs, environment.get("PATH", "")])
        environment["PYTHONIOENCODING"] = WORKER_ENCODING
        environment["PYTHONUTF8"] = "1"
        return environment

    def _wait_ready(self, ready_timeout_sec: float | None) -> None:
        """ready・error・子プロセスの終了のどれかを待つ。ready 以外なら EngineError を送出する。"""
        deadline = None if ready_timeout_sec is None else time.monotonic() + ready_timeout_sec
        while True:
            try:
                timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
                message = self._messages.get(timeout=timeout)
            except queue.Empty:
                raise EngineError(
                    f"文字起こしワーカーの ready を {ready_timeout_sec} 秒待ったが届かない"
                ) from None
            if message is None:
                raise EngineError("文字起こしワーカーが ready の前に終わった")
            if message.type == "ready":
                return
            if message.type == "error":
                raise EngineError(f"文字起こしワーカーがモデルを読めない（{message.payload.get('message')}）")
            logger.warning(f"ready の待ちに知らない種類が届いた（{message.type}）")

    # === 文字起こし ===

    def transcribe(
        self, audio_path: Path, *, on_progress: ProgressFn | None = None, hint: str | None = None
    ) -> list[str]:
        """録音と手がかりを子プロセスへ送信し、区間ごとの文字を受け取る。落ちたら 1 回だけ立て直してやり直す。"""
        with self._lock:
            try:
                return self._exchange(audio_path, on_progress, hint)
            except _WorkerExitedError:
                self._raise_if_stopping()
                logger.warning(f"文字起こしワーカーが落ちたので立て直す（終了コード {self._exit_code()}）")
                self._restart()

            # 立て直したワーカーへ同じ録音を再送する（やり直しは 1 回だけ）
            try:
                return self._exchange(audio_path, on_progress, hint)
            except _WorkerExitedError:
                self._raise_if_stopping()
                # やり直しも落ちた: 次の録音に備えて起動し直してから知らせる
                logger.warning(f"文字起こしワーカーが落ちたので立て直す（終了コード {self._exit_code()}）")
                self._restart()
                raise EngineError("やり直した文字起こしワーカーも異常終了した") from None

    def _exchange(
        self, audio_path: Path, on_progress: ProgressFn | None, hint: str | None
    ) -> list[str]:
        """録音・設定・手がかりを送信し、区間の進みと結果を読む。子プロセスが終わっていれば _WorkerExitedError を送出する。"""
        settings = self._settings
        # 手がかりがあるときだけ hotwords として載せる
        optional: dict[str, str] = {} if hint is None else {"hotwords": hint}
        self._send(
            "transcribe",
            audio_path=str(audio_path),
            language=settings.language,
            beam_size=settings.beam_size,
            best_of=settings.best_of,
            temperature=settings.temperature,
            vad_filter=settings.vad_filter,
            vad_threshold=settings.vad_threshold,
            vad_min_speech_ms=settings.vad_min_speech_ms,
            vad_min_silence_ms=settings.vad_min_silence_ms,
            condition_on_previous_text=settings.condition_on_previous_text,
            no_speech_threshold=settings.no_speech_threshold,
            **optional,
        )
        while True:
            message = self._messages.get()
            if message is None:
                raise _WorkerExitedError
            if message.type == "progress":
                if on_progress is not None:
                    on_progress(message.payload["end"], message.payload["duration"])
            elif message.type == "result":
                return list(message.payload["segments"])
            elif message.type == "error":
                # ワーカーがエラーを返した: 起動し直さずに知らせる
                raise EngineError(f"文字起こしワーカーがエラーを返した（{message.payload.get('message')}）")
            else:
                logger.warning(f"知らない種類が届いた（{message.type}）")

    def _raise_if_stopping(self) -> None:
        """stop で止めている最中なら、立て直さずに EngineError を送出する。"""
        if self._stopping:
            raise EngineError("文字起こしワーカーが終了のために止められた") from None

    def _restart(self) -> None:
        """子プロセスを止め、立て直しの上限をかけて起動し直す。"""
        self._halt()
        self.start(ready_timeout_sec=self._ready_timeout_sec)

    def _exit_code(self) -> int | None:
        """子プロセスの終了コード（まだ終わっていなければ None）。"""
        return None if self._process is None else self._process.poll()

    # === 停止 ===

    def stop(self) -> None:
        """標準入力を閉じて終わりを待ち、待ちきれなければ terminate・kill で止める。文字起こしの最中でも待たない。"""
        # 文字起こしが持つロックは取らない（文字起こしの終わりまで止まらないようにする）。
        # 止めた子プロセスを transcribe が「落ちた」と受けて立て直さないよう、先にマーカーを立てる
        self._stopping = True
        process = self._process
        # 子プロセスが無ければ何もしない
        if process is None:
            return
        self._close_stdin(process)
        try:
            process.wait(timeout=self._stop_timeout_sec)
            return
        except subprocess.TimeoutExpired:
            logger.warning("文字起こしワーカーが終わらないので止めた（terminate）")
        process.terminate()
        try:
            process.wait(timeout=self._stop_timeout_sec)
            return
        except subprocess.TimeoutExpired:
            logger.warning("文字起こしワーカーが終わらないので止めた（kill）")
        process.kill()

    def _halt(self) -> None:
        """子プロセスを terminate で止める（待ちきれなければ kill）。応答しない・落ちた子プロセスの片付け用。"""
        process = self._process
        if process is None:
            return
        self._process = None
        # まだ動いていれば止める
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._stop_timeout_sec)
            except subprocess.TimeoutExpired:
                process.kill()
        self._close_stdin(process)

    @staticmethod
    def _close_stdin(process: subprocess.Popen[str]) -> None:
        """子プロセスの標準入力を閉じる（既に壊れていても気にしない）。"""
        if process.stdin is None:
            return
        try:
            process.stdin.close()
        except OSError:
            # 子プロセスが先に終わっていて閉じられない: 片付けるだけなので無視する
            logger.debug("標準入力を閉じられなかった")

    # === 子プロセスとのやり取り ===

    def _send(self, message_type: str, **payload: object) -> None:
        """子プロセスの標準入力へメッセージを 1 行書く。書けなければ _WorkerExitedError を送出する。"""
        process = self._process
        # 子プロセスが無い・終わっている
        if process is None or process.stdin is None or process.poll() is not None:
            raise _WorkerExitedError
        try:
            process.stdin.write(WorkerMessage(type=message_type, payload=payload).to_line())
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            # 書けない（パイプが壊れた・閉じた）: 落ちたものとして扱う
            raise _WorkerExitedError from error

    @staticmethod
    def _pump_stdout(
        process: subprocess.Popen[str], messages: queue.Queue[WorkerMessage | None]
    ) -> None:
        """標準出力を 1 行ずつメッセージにしてキューへ入れる。終わったら None を入れる。"""
        stdout: IO[str] = process.stdout  # type: ignore[assignment]
        for line in iter(stdout.readline, ""):
            try:
                messages.put(WorkerMessage.from_line(line))
            except ValidationError:
                # メッセージでない行（ライブラリが標準出力へ書いた文字など）は飛ばす
                logger.warning(f"文字起こしワーカーの標準出力にメッセージでない行があった（{line.strip()}）")
        messages.put(None)

    @staticmethod
    def _forward_stderr(process: subprocess.Popen[str]) -> None:
        """標準エラーの行をロガーへ流す。"""
        stderr: IO[str] = process.stderr  # type: ignore[assignment]
        for line in stderr:
            if line.strip():
                logger.info(f"[ワーカー] {line.rstrip()}")
