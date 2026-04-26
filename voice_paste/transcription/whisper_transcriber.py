"""faster-whisper による文字起こし実装モジュール。

Interface: transcribable.py
Implementation: whisper_transcriber.py
"""

import gc
from pathlib import Path
from typing import Callable

from faster_whisper import WhisperModel

from voice_paste.transcription.transcribable import Transcribable
from voice_paste.logger import get_logger
from voice_paste import config

logger = get_logger(__name__)


class WhisperTranscriber(Transcribable):
    """faster-whisper を使用した文字起こし実装クラス。"""

    def __init__(self) -> None:
        """WhisperModel を初期化する。"""
        self._session_count = 0
        self._model = self._load_model()

    def _load_model(self) -> WhisperModel:
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
        return model

    def transcribe(
        self,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None = None,
    ) -> str:
        """
        音声ファイルを文字起こしする。

        :param audio_file: 文字起こし対象の音声ファイルパス
        :param on_segment: セグメント処理ごとに呼ばれるコールバック（UI更新用）
        :return: 文字起こし結果のテキスト
        """
        logger.info("Starting transcription: file=%s", audio_file)

        vad_parameters = {
            "threshold": config.WHISPER_VAD_THRESHOLD,
            "min_speech_duration_ms": config.WHISPER_VAD_MIN_SPEECH_MS,
            "min_silence_duration_ms": config.WHISPER_VAD_MIN_SILENCE_MS,
        } if config.WHISPER_VAD_FILTER else None

        segments, info = self._model.transcribe(
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

        # セグメントごとに改行で結合（セグメント処理ごとにコールバック）
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

        self._session_count += 1
        self._maybe_reinit_model()

        return result

    def _maybe_reinit_model(self) -> None:
        """セッション数が閾値に達したらモデルを再初期化してGPUメモリを解放する。"""
        interval = config.WHISPER_REINIT_INTERVAL
        if interval <= 0:
            gc.collect()
            return
        if self._session_count % interval == 0:
            logger.info(
                "Reinitializing WhisperModel to release GPU memory (session=%d, interval=%d)",
                self._session_count,
                interval,
            )
            del self._model
            gc.collect()
            self._model = self._load_model()
        else:
            gc.collect()
