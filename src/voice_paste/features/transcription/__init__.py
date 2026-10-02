"""文字起こしの機能。"""

from voice_paste.features.transcription.service import transcribe
from voice_paste.features.transcription.types import EngineFn, EngineName

__all__ = ["EngineFn", "EngineName", "transcribe"]
