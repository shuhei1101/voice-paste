"""マイクの録音の機能。"""

from voice_paste.features.recording.segmenter import Segmenter
from voice_paste.features.recording.service import Recorder

__all__ = ["Recorder", "Segmenter"]
