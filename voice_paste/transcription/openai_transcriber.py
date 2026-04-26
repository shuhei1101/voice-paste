"""OpenAI Whisper API による文字起こし実装モジュール。

Interface: transcribable.py
Implementation: openai_transcriber.py
"""

from pathlib import Path
from typing import Callable

from voice_paste.transcription.transcribable import Transcribable
from voice_paste.logger import get_logger
from voice_paste import config

logger = get_logger(__name__)


class OpenAITranscriber(Transcribable):
    """OpenAI Whisper API を使用した文字起こし実装クラス。"""

    def __init__(self) -> None:
        from openai import OpenAI

        if not config.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY が設定されていません。"
                ".env に OPENAI_API_KEY=sk-... を追加してください。"
            )
        self._client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("OpenAITranscriber initialized.")

    def transcribe(
        self,
        audio_file: Path,
        on_segment: Callable[[float | None, float | None], None] | None = None,
    ) -> str:
        """
        音声ファイルを OpenAI Whisper API で文字起こしする。

        :param audio_file: 文字起こし対象の音声ファイルパス
        :param on_segment: セグメントごとに呼ばれるコールバック（オーバーレイ更新用）
        :return: 文字起こし結果のテキスト（セグメント間は改行で結合）
        """
        logger.info("Starting OpenAI transcription: file=%s", audio_file)

        with open(audio_file, "rb") as f:
            response = self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=config.WHISPER_LANGUAGE,
                temperature=config.WHISPER_TEMPERATURE,
                response_format="verbose_json",
            )

        segments = getattr(response, "segments", None) or []
        total_duration: float | None = getattr(response, "duration", None)
        lines: list[str] = []
        for seg in segments:
            text = seg.text.strip() if hasattr(seg, "text") else ""
            if text:
                lines.append(text)
            if on_segment:
                seg_end = getattr(seg, "end", None)
                remaining = max(0.0, total_duration - seg_end) if (total_duration is not None and seg_end is not None) else None
                on_segment(remaining, total_duration)

        # セグメントが取れない場合は全文テキストにフォールバック
        if not lines:
            fallback = getattr(response, "text", "") or ""
            result = fallback.strip()
            if on_segment:
                on_segment(None, None)
        else:
            result = "\n".join(lines)

        logger.info("OpenAI transcription completed: %d segments, %d chars", len(lines), len(result))
        return result
