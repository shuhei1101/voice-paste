"""ブラウザの文字起こしの API の route（POST /web/transcriptions・GET /web/transcriptions/{job_id}）。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile

from voice_paste.features.web_transcription.schemas import (
    CreateWebTranscriptionResponse,
    WebTranscriptionStatus,
)
from voice_paste.features.web_transcription.service import accept_audio
from voice_paste.features.web_transcription.types import WebApiDeps

router = APIRouter()


def get_web_api_deps(request: Request) -> WebApiDeps:
    """app.state.web_api に置かれたブラウザの API の依存を返す。"""
    return request.app.state.web_api  # type: ignore[no-any-return]


@router.post("/web/transcriptions", status_code=HTTPStatus.ACCEPTED)
def create_web_transcription_route(
    audio: UploadFile,
    deps: Annotated[WebApiDeps, Depends(get_web_api_deps)],
) -> CreateWebTranscriptionResponse:
    """受けた音声を積み、ジョブの ID を返す。"""
    # 受け付けの失敗（読めない・待ちが上限）は例外ハンドラが HTTP に変える
    job = accept_audio(audio.file, deps=deps)
    return CreateWebTranscriptionResponse(job_id=job.id)


@router.get("/web/transcriptions/{job_id}")
def get_web_transcription_route(
    job_id: str,
    deps: Annotated[WebApiDeps, Depends(get_web_api_deps)],
) -> WebTranscriptionStatus:
    """ジョブの今の状態と、終わっていれば起こした文字か失敗の理由を返す。"""
    # ジョブが無ければ WebJobNotFoundError を例外ハンドラが 404 にする
    job = deps.queue.get(job_id)
    return WebTranscriptionStatus(
        job_id=job.id,
        state=job.state,
        progress=job.progress,
        text=job.text,
        error=job.error,
    )
