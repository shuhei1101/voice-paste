"""録音セッションの API の route（POST /sessions・/stop・/complete）。"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from voice_paste.features.session.schemas import StartSessionRequest, StartSessionResponse
from voice_paste.features.session.types import SessionApiDeps
from voice_paste.shared.errors import CallbackNotAllowedError, GlossaryPresetNotFoundError
from voice_paste.shared.types import Entry

logger = logging.getLogger(__name__)

router = APIRouter()


def get_session_api_deps(request: Request) -> SessionApiDeps:
    """app.state.session_api に置かれた録音セッションの API の依存を返す。"""
    return request.app.state.session_api  # type: ignore[no-any-return]


@router.post("/sessions", status_code=HTTPStatus.ACCEPTED)
def start_session_route(
    body: StartSessionRequest,
    deps: Annotated[SessionApiDeps, Depends(get_session_api_deps)],
) -> StartSessionResponse:
    """コールバック先と用語集のプリセットを確かめて、API の録音を始め、録音セッションの ID を返す。"""
    # 1. コールバック先のホストが許されなければ開始しない
    callback_url = str(body.callback_url)
    if not deps.is_callback_allowed(callback_url):
        raise CallbackNotAllowedError("コールバック先のホストが許されていません")

    # 2. 指定した用語集のプリセットが一覧に無ければ、録音を始めずに断る
    if body.glossary_preset is not None and not deps.glossary_preset_exists(body.glossary_preset):
        logger.warning(f"用語集のプリセットが無いため開始を断った（{body.glossary_preset}）")
        raise GlossaryPresetNotFoundError(
            f"用語集のプリセットが無い（{body.glossary_preset}）"
        )

    # 3. 録音（continuous なら連続録音）を始めて録音セッションの ID を返す（処理中・マイクの失敗は例外ハンドラが HTTP に変える）
    session = deps.session_manager.start(
        entry=Entry.API,
        callback_url=callback_url,
        continuous=body.continuous,
        glossary_preset=body.glossary_preset,
    )
    return StartSessionResponse(session_id=session.id)


@router.post("/sessions/{session_id}/stop", status_code=HTTPStatus.OK)
def stop_session_route(
    session_id: str,
    deps: Annotated[SessionApiDeps, Depends(get_session_api_deps)],
) -> None:
    """API の録音を止める。"""
    deps.session_manager.stop(session_id)


@router.post("/sessions/{session_id}/complete", status_code=HTTPStatus.ACCEPTED)
def complete_session_route(
    session_id: str,
    deps: Annotated[SessionApiDeps, Depends(get_session_api_deps)],
) -> None:
    """API の録音を確定して、文字起こしから返送までを始める。"""
    deps.session_manager.complete(session_id)
