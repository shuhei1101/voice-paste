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

from tests.unit.voice_paste.server.helpers import PORT, TOKEN, WEB_ORIGIN

VALID_HEADERS = {"host": f"127.0.0.1:{PORT}", "authorization": f"Bearer {TOKEN}"}


WEB_HEADERS = {"host": f"localhost:{PORT}"}
"""ゲートウェイを通した /web/ の要求のヘッダー（Host は localhost:{ポート}。トークンは付かない）。"""


def _request(headers: dict[str, str], method: str, path: str) -> Request:
    """method と path の要求を、headers を付けて作る。"""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        "scheme": "http",
        "server": ("127.0.0.1", PORT),
        "client": ("127.0.0.1", 50000),
        "http_version": "1.1",
    }
    return Request(scope)


def _dispatch(
    headers: dict[str, str], method: str = "POST", path: str = "/sessions"
) -> tuple[Response, AsyncMock]:
    """守りに method と path の要求を headers つきで通し、返った応答と次の処理（call_next）の Mock を返す。"""
    from voice_paste.server.middleware import RequestGuardMiddleware

    middleware = RequestGuardMiddleware(
        MagicMock(), token=SecretStr(TOKEN), port=PORT, allowed_web_origins=[WEB_ORIGIN]
    )
    call_next = AsyncMock(return_value=Response(status_code=204))
    response = asyncio.run(middleware.dispatch(_request(headers, method, path), call_next))
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


def test_dispatch_when_web_get_without_origin() -> None:
    """/web/ の下の Origin の無い GET はトークン無しで通す（正常系）。"""
    # 実行
    response, call_next = _dispatch(WEB_HEADERS, method="GET", path="/web/")

    # 検証
    call_next.assert_awaited_once()
    assert response.status_code == 204


def test_dispatch_when_web_post_with_allowed_origin() -> None:
    """/web/ の下の許す Origin の POST を通す（正常系）。"""
    # 実行
    response, call_next = _dispatch(
        {**WEB_HEADERS, "origin": WEB_ORIGIN}, method="POST", path="/web/transcriptions"
    )

    # 検証
    call_next.assert_awaited_once()
    assert response.status_code == 204


@pytest.mark.parametrize(
    ("headers", "method", "path"),
    [
        pytest.param(WEB_HEADERS, "POST", "/web/transcriptions", id="post_without_origin"),
        pytest.param(
            {**WEB_HEADERS, "origin": "http://evil.example"},
            "GET",
            "/web/",
            id="get_with_other_origin",
        ),
    ],
)
def test_dispatch_when_web_post_without_origin(
    headers: dict[str, str], method: str, path: str
) -> None:
    """/web/ の下の Origin の無い POST・許さない Origin は 403（異常系）。"""
    # 実行
    response, call_next = _dispatch(headers, method=method, path=path)

    # 検証
    assert response.status_code == 403
    call_next.assert_not_awaited()


def test_dispatch_when_sessions_with_allowed_origin() -> None:
    """/web/ の外は許す Origin でも 403（異常系）。"""
    # 実行
    response, call_next = _dispatch({**VALID_HEADERS, "origin": WEB_ORIGIN})

    # 検証
    assert response.status_code == 403
    call_next.assert_not_awaited()
