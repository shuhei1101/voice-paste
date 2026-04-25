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
        prompt: str = "",
        on_segment: Callable[[], None] | None = None,
    ) -> str:
        """
        音声ファイルを OpenAI Whisper API で文字起こしする。

        :param audio_file: 文字起こし対象の音声ファイルパス
        :param prompt: Whisper API に渡す initial_prompt（用語集等）
        :param on_segment: 文字起こし完了時に一度呼ばれるコールバック
        :return: 文字起こし結果のテキスト
        """
        logger.info("Starting OpenAI transcription: file=%s", audio_file)

        with open(audio_file, "rb") as f:
            response = self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=config.WHISPER_LANGUAGE,
                prompt=prompt if prompt else None,
                response_format="text",
            )

        result = response.strip() if isinstance(response, str) else str(response).strip()

        if on_segment:
            on_segment()

        logger.info("OpenAI transcription completed: %d chars", len(result))
        return result
