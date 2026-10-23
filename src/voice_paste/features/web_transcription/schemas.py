"""ブラウザの文字起こしの API のレスポンス。"""

from __future__ import annotations

from pydantic import BaseModel

from voice_paste.features.web_transcription.types import JobState


class CreateWebTranscriptionResponse(BaseModel):
    """POST /web/transcriptions の 202 の body。"""

    job_id: str
    """積んだジョブの ID。"""


class WebTranscriptionStatus(BaseModel):
    """GET /web/transcriptions/{job_id} の 200 の body。"""

    job_id: str
    """ジョブの ID。"""

    state: JobState
    """ジョブの状態。"""

    progress: float
    """進み具合（0.0〜1.0）。"""

    text: str | None
    """done のときの補正した文字。"""

    error: str | None
    """failed のときの失敗の理由。"""
