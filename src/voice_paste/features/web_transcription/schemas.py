"""ブラウザの文字起こしの API のレスポンス。"""

from __future__ import annotations

from pydantic import BaseModel

from voice_paste.features.web_transcription.types import JobState


class CreateWebTranscriptionResponse(BaseModel):
    """POST /web/transcriptions の 202 の body。"""

    job_id: str
    """積んだジョブの ID。"""


class WebGlossaryPresetsResponse(BaseModel):
    """GET /web/glossary-presets の 200 の body。"""

    presets: list[str]
    """用語集のプリセットの名前の一覧（設定の並びのまま）。"""

    active: str
    """設定で選んでいるプリセットの名前。"""


class WebTranscriptionStatus(BaseModel):
    """GET /web/transcriptions/{job_id} の 200 の body。"""

    job_id: str
    """ジョブの ID。"""

    state: JobState
    """ジョブの状態。"""

    progress: float
    """進み具合（0.0〜1.0）。"""

    reports_progress: bool
    """設定の文字起こしのエンジンが途中の進みを返すか（false のとき progress は running の間も 0.0）。"""

    text: str | None
    """done のときの補正した文字。"""

    error: str | None
    """failed のときの失敗の理由。"""
