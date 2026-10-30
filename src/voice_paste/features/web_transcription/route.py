"""ブラウザの文字起こしの API の route（POST /web/transcriptions・GET /web/transcriptions/{job_id}・GET /web/glossary-presets）。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile

from voice_paste.features.web_transcription.schemas import (
    CreateWebTranscriptionResponse,
    WebGlossaryPresetsResponse,
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
    glossary_preset: Annotated[str | None, Form()] = None,
) -> CreateWebTranscriptionResponse:
    """受けた音声を指定された用語集のプリセットと共に積み、ジョブの ID を返す。"""
    # 受け付けの失敗（読めない・待ちが上限・一覧に無いプリセット）は例外ハンドラが HTTP に変える
    job = accept_audio(audio.file, deps=deps, glossary_preset=glossary_preset)
    return CreateWebTranscriptionResponse(job_id=job.id)


@router.get("/web/glossary-presets")
def get_web_glossary_presets_route(
    deps: Annotated[WebApiDeps, Depends(get_web_api_deps)],
) -> WebGlossaryPresetsResponse:
    """画面の選択欄に並べる用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前を返す。"""
    # Host・Origin の守りは要求の守りのミドルウェアが `/web/` の下として持つ
    choices = deps.list_glossary_presets()
    return WebGlossaryPresetsResponse(presets=choices.presets, active=choices.active)


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
        reports_progress=deps.reports_progress,
        text=job.text,
        error=job.error,
    )
