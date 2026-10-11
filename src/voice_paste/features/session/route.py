"""セッションの API の route（POST /sessions・/stop・/complete）。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from voice_paste.features.session.schemas import StartSessionRequest, StartSessionResponse
from voice_paste.features.session.types import SessionApiDeps
from voice_paste.shared.errors import CallbackNotAllowedError
from voice_paste.shared.types import Entry

router = APIRouter()


def get_session_api_deps(request: Request) -> SessionApiDeps:
    """app.state.session_api に置かれたセッションの API の依存を返す。"""
    return request.app.state.session_api  # type: ignore[no-any-return]


@router.post("/sessions", status_code=HTTPStatus.ACCEPTED)
def start_session_route(
    body: StartSessionRequest,
    deps: Annotated[SessionApiDeps, Depends(get_session_api_deps)],
) -> StartSessionResponse:
    """返送先を確かめて、API の録音を始め、セッションの ID を返す。"""
    # 1. 返送先のホストが許されなければ開始しない
    callback_url = str(body.callback_url)
    if not deps.is_callback_allowed(callback_url):
        raise CallbackNotAllowedError("返送先のホストが許されていません")

    # 2. 録音（continuous なら連続録音）を始めてセッションの ID を返す（処理中・マイクの失敗は例外ハンドラが HTTP に変える）
    session = deps.session_manager.start(
        entry=Entry.API, callback_url=callback_url, continuous=body.continuous
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
