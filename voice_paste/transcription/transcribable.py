"""文字起こしインターフェース定義モジュール。

Interface: transcribable.py
Implementation: whisper_transcriber.py
"""

from abc import ABC, abstractmethod
from pathlib import Path


class Transcribable(ABC):
    """文字起こし処理のインターフェース。"""

    @abstractmethod
    def transcribe(self, audio_file: Path, prompt: str = "") -> str:
        """
        音声ファイルを文字起こしする。

        :param audio_file: 文字起こし対象の音声ファイルパス
        :param prompt: Whisperに渡す初期プロンプト（用語集等）
        :return: 文字起こし結果のテキスト
        """
