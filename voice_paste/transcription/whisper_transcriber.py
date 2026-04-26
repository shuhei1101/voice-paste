"""faster-whisper による文字起こし実装モジュール。

Interface: transcribable.py
Implementation: whisper_transcriber.py

CUDAコンテキストを1本の永続ワーカースレッドに固定することで、
クロススレッドCUDA操作によるクラッシュを防ぐ。
"""

import queue
import threading
from pathlib import Path
from typing import Callable

from faster_whisper import WhisperModel

from voice_paste.transcription.transcribable import Transcribable
from voice_paste.logger import get_logger
from voice_paste import config

logger = get_logger(__name__)


class WhisperTranscriber(Transcribable):
    """faster-whisper を使用した文字起こし実装クラス。

    WhisperModel の生成・使用を同一の永続ワーカースレッド内に閉じ込め、
    CUDAコンテキストのクロススレッド問題を回避する。
    """

    def __init__(self) -> None:
        self._request_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()
        self._model_ready = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        # モデルロード完了まで呼び出し元をブロック（起動時のローディング表示のため）
        self._model_ready.wait()

    def _worker_loop(self) -> None:
        """CUDAコンテキストを保有する永続ワーカースレッド。"""
        logger.info(
            "Initializing WhisperModel: model=%s, device=%s, compute_type=%s",
            config.WHISPER_MODEL,
            config.WHISPER_DEVICE,
            config.WHISPER_COMPUTE_TYPE,
        )
        model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
            cpu_threads=config.WHISPER_CPU_THREADS,
            num_workers=config.WHISPER_NUM_WORKERS,
        )
        logger.info("WhisperModel initialized successfully.")
        self._model_ready.set()

        while True:
            job = self._request_queue.get()
            if job is None:
                break
            audio_file, on_segment = job
            try:
                result = self._do_transcribe(model, audio_file, on_segment)
                self._result_queue.put(("ok", result))
            except Exception as exc:
                logger.exception("Transcription error in worker thread.")
                self._result_queue.put(("error", exc))

    def _do_transcribe(
        self,
        model: WhisperModel,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None,
    ) -> str:
        logger.info("Starting transcription: file=%s", audio_file)

        vad_parameters = {
            "threshold": config.WHISPER_VAD_THRESHOLD,
            "min_speech_duration_ms": config.WHISPER_VAD_MIN_SPEECH_MS,
            "min_silence_duration_ms": config.WHISPER_VAD_MIN_SILENCE_MS,
        } if config.WHISPER_VAD_FILTER else None

        segments, info = model.transcribe(
            str(audio_file),
            language=config.WHISPER_LANGUAGE,
            beam_size=config.WHISPER_BEAM_SIZE,
            best_of=config.WHISPER_BEST_OF,
            temperature=config.WHISPER_TEMPERATURE,
            vad_filter=config.WHISPER_VAD_FILTER,
            vad_parameters=vad_parameters,
            condition_on_previous_text=config.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            no_speech_threshold=config.WHISPER_NO_SPEECH_THRESHOLD,
        )

        logger.info(
            "Transcription info: language=%s, probability=%.2f, duration=%.1fs",
            info.language,
            info.language_probability,
            info.duration,
        )

        lines: list[str] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                lines.append(text)
            if on_segment:
                remaining = max(0.0, info.duration - segment.end)
                on_segment(remaining, info.duration)
        result = "\n".join(lines)
        logger.info("Transcription completed: %d chars, %d segments", len(result), len(lines))
        return result

    def transcribe(
        self,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None = None,
    ) -> str:
        """音声ファイルを文字起こしする。実処理はワーカースレッドに委譲する。"""
        self._request_queue.put((audio_file, on_segment))
        status, value = self._result_queue.get()
        if status == "error":
            raise value
        return value
