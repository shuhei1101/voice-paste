"""外の端末のブラウザから受けた音声を、ジョブに積んで 1 件ずつ起こす機能。"""

from voice_paste.features.web_transcription.route import router
from voice_paste.features.web_transcription.service import WebJobQueue, accept_audio
from voice_paste.features.web_transcription.types import (
    GlossaryPresetChoices,
    JobState,
    WebApiDeps,
    WebJob,
    WebTranscriptionDeps,
)

__all__ = [
    "GlossaryPresetChoices",
    "JobState",
    "WebApiDeps",
    "WebJob",
    "WebJobQueue",
    "WebTranscriptionDeps",
    "accept_audio",
    "router",
]
