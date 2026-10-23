"""共通の例外を RFC 9457 の application/problem+json へ変える。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from voice_paste.shared.errors import (
    AudioUnreadableError,
    CallbackNotAllowedError,
    MicrophoneUnavailableError,
    RequestBodyTooLargeError,
    SessionBusyError,
    SessionConflictError,
    SessionNotFoundError,
    WebJobNotFoundError,
    WebQueueFullError,
)

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE: str = "application/problem+json"
"""RFC 9457 のエラー応答の Content-Type。"""

type ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]
"""例外を HTTP の応答に変える関数。"""


def problem_response(status: HTTPStatus, detail: str) -> JSONResponse:
    """RFC 9457 の problem+json の応答を作る。"""
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": "about:blank",
            "title": status.phrase,
            "status": status.value,
            "detail": detail,
        },
    )


def _handler_for(status: HTTPStatus) -> ExceptionHandler:
    """例外のメッセージを detail にして status の応答を返す例外ハンドラを作る。"""

    async def _handle(_request: Request, error: Exception) -> JSONResponse:
        return problem_response(status, str(error))

    return _handle


async def _handle_validation_error(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    """入力の検証の失敗を、入力の値を載せずに 400 にする。"""
    # どの項目がなぜ合わないかだけを書く（受け取った値は応答に出さない）
    reasons = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return problem_response(HTTPStatus.BAD_REQUEST, "; ".join(reasons))


async def _handle_http_exception(
    _request: Request, error: StarletteHTTPException
) -> JSONResponse:
    """Starlette の HTTPException を、そのステータスの problem+json にする。"""
    status = HTTPStatus(error.status_code)
    return problem_response(status, str(error.detail))


async def _handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
    """想定していない例外を、中身を載せずに 500 にする。"""
    logger.error("想定していない例外", exc_info=error)
    return problem_response(HTTPStatus.INTERNAL_SERVER_ERROR, "サーバーで想定していない問題が起きました")


def register_exception_handlers(app: FastAPI) -> None:
    """共通の例外を problem+json へ変えるハンドラを app に登録する。"""
    # 1. 呼び出し側の誤り・状態の例外を、対応するステータスへ
    app.add_exception_handler(CallbackNotAllowedError, _handler_for(HTTPStatus.BAD_REQUEST))
    app.add_exception_handler(
        RequestValidationError,
        _handle_validation_error,  # type: ignore[arg-type] 受ける例外の型を絞った関数
    )
    app.add_exception_handler(SessionNotFoundError, _handler_for(HTTPStatus.NOT_FOUND))
    app.add_exception_handler(WebJobNotFoundError, _handler_for(HTTPStatus.NOT_FOUND))
    app.add_exception_handler(
        RequestBodyTooLargeError, _handler_for(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    )
    app.add_exception_handler(
        AudioUnreadableError, _handler_for(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    )
    app.add_exception_handler(SessionBusyError, _handler_for(HTTPStatus.CONFLICT))
    app.add_exception_handler(SessionConflictError, _handler_for(HTTPStatus.CONFLICT))
    app.add_exception_handler(
        MicrophoneUnavailableError, _handler_for(HTTPStatus.SERVICE_UNAVAILABLE)
    )
    app.add_exception_handler(WebQueueFullError, _handler_for(HTTPStatus.SERVICE_UNAVAILABLE))
    # StaticFiles の 404 などの HTTPException を、そのステータスの problem+json にする
    app.add_exception_handler(
        StarletteHTTPException,
        _handle_http_exception,  # type: ignore[arg-type] 受ける例外の型を絞った関数
    )

    # 2. それ以外の例外は 500 にする
    app.add_exception_handler(Exception, _handle_unexpected_error)
