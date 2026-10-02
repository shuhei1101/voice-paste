"""server/middleware.py（RequestGuardMiddleware.dispatch）の単体テスト。

次の処理（call_next）は Mock にして、守りが通した・断ったかだけを確かめる。
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

from tests.unit.voice_paste.server.helpers import PORT, TOKEN

VALID_HEADERS = {"host": f"127.0.0.1:{PORT}", "authorization": f"Bearer {TOKEN}"}


def _request(headers: dict[str, str]) -> Request:
    """POST /sessions の要求を、headers を付けて作る。"""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/sessions",
        "raw_path": b"/sessions",
        "query_string": b"",
        "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        "scheme": "http",
        "server": ("127.0.0.1", PORT),
        "client": ("127.0.0.1", 50000),
        "http_version": "1.1",
    }
    return Request(scope)


def _dispatch(headers: dict[str, str]) -> tuple[Response, AsyncMock]:
    """守りに headers の要求を通し、返った応答と次の処理（call_next）の Mock を返す。"""
    from voice_paste.server.middleware import RequestGuardMiddleware

    middleware = RequestGuardMiddleware(MagicMock(), token=SecretStr(TOKEN), port=PORT)
    call_next = AsyncMock(return_value=Response(status_code=204))
    response = asyncio.run(middleware.dispatch(_request(headers), call_next))
    return response, call_next


def test_dispatch() -> None:
    """正しい要求は通す（正常系）。"""
    # 実行
    response, call_next = _dispatch(VALID_HEADERS)

    # 検証
    call_next.assert_awaited_once()
    assert response.status_code == 204


def test_dispatch_when_origin_present(caplog: pytest.LogCaptureFixture) -> None:
    """Origin 付きは 403（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    response, call_next = _dispatch({**VALID_HEADERS, "origin": "http://evil.example"})

    # 検証
    assert response.status_code == 403
    call_next.assert_not_awaited()
    assert "WARNING" in caplog.text
    assert TOKEN not in caplog.text


def test_dispatch_when_host_mismatch() -> None:
    """ほかの Host は 403（正常系）。"""
    # 実行
    response, call_next = _dispatch({**VALID_HEADERS, "host": "evil.example"})

    # 検証
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"host": f"127.0.0.1:{PORT}"}, id="no_authorization"),
        pytest.param(
            {"host": f"127.0.0.1:{PORT}", "authorization": "Bearer wrong-token"},
            id="wrong_token",
        ),
    ],
)
def test_dispatch_when_token_mismatch(headers: dict[str, str]) -> None:
    """トークンが合わなければ 401（正常系）。"""
    # 実行
    response, call_next = _dispatch(headers)

    # 検証
    assert response.status_code == 401
    call_next.assert_not_awaited()
