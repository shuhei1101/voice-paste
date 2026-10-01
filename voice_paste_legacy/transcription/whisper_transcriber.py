"""faster-whisper による文字起こし実装モジュール（サブプロセス隔離版）。

Interface: transcribable.py
Implementation: whisper_transcriber.py

WhisperModel を独立サブプロセスで実行することで、CTranslate2 / cuBLAS が
RTX 50系（Blackwell）でクラッシュしてもメインプロセスは生き残れるようにする。
faster-whisper #1293 の公式ワークアラウンド「subprocess isolation」相当。
"""

import atexit
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from voice_paste.transcription.transcribable import Transcribable
from voice_paste.logger import get_logger
from voice_paste import config
from voice_paste.constants import LOG_DIR

logger = get_logger(__name__)

_WORKER_SCRIPT = Path(__file__).parent / "whisper_worker.py"
_CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW相当（コンソール非表示）


class WorkerCrashed(RuntimeError):
    """ワーカーサブプロセスがクラッシュ・予期せず終了した時に投げる。"""


class WhisperTranscriber(Transcribable):
    """faster-whisper をサブプロセスで実行するクラス。

    クラッシュ時は自動的にサブプロセスを再起動する。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._start_worker()
        atexit.register(self._stop_worker)

    def _start_worker(self) -> None:
        """ワーカーサブプロセスを起動し、モデルロード完了まで待つ。"""
        logger.info("Starting whisper worker subprocess.")
        env = os.environ.copy()
        env["VOICE_PASTE_LOG_DIR"] = str(LOG_DIR)
        # ワーカー側でPythonがUTF-8で標準入出力を扱うように
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")

        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0

        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )

        # stderrを別スレッドで読み続けてvoice_pasteのloggerに転送
        self._stderr_thread = threading.Thread(
            target=self._forward_stderr, daemon=True
        )
        self._stderr_thread.start()

        # 初期化リクエストを送る
        init_req = {
            "action": "init",
            "model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "cpu_threads": config.WHISPER_CPU_THREADS,
            "num_workers": config.WHISPER_NUM_WORKERS,
        }
        self._send(init_req)

        # ready イベントを待つ
        msg = self._recv()
        if msg is None:
            raise WorkerCrashed("Worker died before ready signal.")
        if msg.get("event") != "ready":
            raise RuntimeError(f"Unexpected event from worker: {msg}")
        logger.info("Whisper worker subprocess ready (pid=%s).", self._proc.pid)

    def _forward_stderr(self) -> None:
        """ワーカーのstderr出力をvoice_pasteのloggerに転送する。"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    logger.info("[worker] %s", line)
        except Exception:
            pass

    def _send(self, obj: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise WorkerCrashed("Worker not running.")
        try:
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise WorkerCrashed(f"Failed to send request: {exc}")

    def _recv(self) -> dict | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        line = self._proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Non-JSON output from worker: %s", line.strip())
            return self._recv()

    def transcribe(
        self,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None = None,
    ) -> str:
        """音声ファイルを文字起こしする。サブプロセスがクラッシュしたら1回再試行する。"""
        with self._lock:
            try:
                return self._transcribe_once(audio_file, on_segment)
            except WorkerCrashed as exc:
                logger.warning("Worker crashed (%s). Restarting and retrying.", exc)
                self._restart_worker()
                return self._transcribe_once(audio_file, on_segment)

    def _transcribe_once(
        self,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None,
    ) -> str:
        if self._proc is None or self._proc.poll() is not None:
            logger.warning("Worker not running, restarting.")
            self._restart_worker()

        logger.info("Starting transcription: file=%s", audio_file)

        req = {
            "action": "transcribe",
            "audio_file": str(audio_file),
            "language": config.WHISPER_LANGUAGE,
            "beam_size": config.WHISPER_BEAM_SIZE,
            "best_of": config.WHISPER_BEST_OF,
            "temperature": config.WHISPER_TEMPERATURE,
            "vad_filter": config.WHISPER_VAD_FILTER,
            "vad_threshold": config.WHISPER_VAD_THRESHOLD,
            "vad_min_speech_ms": config.WHISPER_VAD_MIN_SPEECH_MS,
            "vad_min_silence_ms": config.WHISPER_VAD_MIN_SILENCE_MS,
            "condition_on_previous_text": config.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            "no_speech_threshold": config.WHISPER_NO_SPEECH_THRESHOLD,
        }
        self._send(req)

        info: dict | None = None
        while True:
            msg = self._recv()
            if msg is None:
                raise WorkerCrashed("Worker died during transcription.")
            event = msg.get("event")
            if event == "info":
                info = msg
                logger.info(
                    "Transcription info: language=%s, probability=%.2f, duration=%.1fs",
                    msg.get("language"),
                    msg.get("language_probability", 0.0),
                    msg.get("duration", 0.0),
                )
            elif event == "segment":
                if on_segment and info is not None:
                    duration = msg.get("duration", 0.0)
                    end = msg.get("end", 0.0)
                    remaining = max(0.0, duration - end)
                    on_segment(remaining, duration)
            elif event == "result":
                text = msg.get("text", "")
                logger.info(
                    "Transcription completed: %d chars, %d segments",
                    len(text),
                    msg.get("segments", 0),
                )
                return text
            elif event == "error":
                raise RuntimeError(msg.get("message", "Unknown worker error"))
            else:
                logger.warning("Unknown event from worker: %s", msg)

    def _restart_worker(self) -> None:
        """ワーカーサブプロセスを停止して再起動する。"""
        self._stop_worker()
        self._start_worker()

    def _stop_worker(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self._send({"action": "shutdown"})
                self._proc.wait(timeout=3)
            except Exception:
                pass
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
