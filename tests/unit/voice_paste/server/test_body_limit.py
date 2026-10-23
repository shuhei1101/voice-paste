"""server/body_limit.py（BodyLimitMiddleware.__call__）の単体テスト。

純粋な ASGI middleware のため、次の ASGI アプリは本文を最後まで読むか呼ばれたかを控える関数にして、
scope・receive・send を直接渡して確かめる。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

LIMIT = 1000
"""テストで差し替える本文の上限（バイト）。"""

WEB_PATH = "/web/transcriptions"


def _scope(path: str, content_length: int | None) -> dict[str, Any]:
    """POST の http の scope を、content_length があればその Content-Length つきで作る。"""
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
    }


def _receive_from(chunks: list[int]) -> Callable[[], Awaitable[dict[str, Any]]]:
    """chunks の大きさ（バイト）の本文を順に返し、最後の 1 つで more_body を False にする receive を返す。"""
    messages = [
        {"type": "http.request", "body": b"x" * size, "more_body": index < len(chunks) - 1}
        for index, size in enumerate(chunks)
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    return receive


class _NextApp:
    """本文を最後まで読み、呼ばれたことと読んだバイト数を控える次の ASGI アプリ。"""

    def __init__(self) -> None:
        self.called = False
        self.received = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401 ASGI の型
        self.called = True
        while True:
            message = await receive()
            self.received += len(message["body"])
            if not message["more_body"]:
                return


def _run(
    next_app: _NextApp, scope: dict[str, Any], chunks: list[int]
) -> list[dict[str, Any]]:
    """上限 LIMIT の middleware に要求を通し、send に渡された応答のメッセージを返す。"""
    from voice_paste.server.body_limit import BodyLimitMiddleware

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    middleware = BodyLimitMiddleware(next_app, limit=LIMIT)
    asyncio.run(middleware(scope, _receive_from(chunks), send))
    return sent


@pytest.mark.parametrize(
    ("content_length", "chunks"),
    [
        pytest.param(LIMIT - 1, [LIMIT - 1], id="with_content_length"),
        pytest.param(None, [LIMIT // 2, LIMIT // 2 - 1], id="chunked"),
    ],
)
def test_call(content_length: int | None, chunks: list[int]) -> None:
    """上限未満は通す（正常系）。"""
    # 準備
    next_app = _NextApp()

    # 実行
    _run(next_app, _scope(WEB_PATH, content_length), chunks)

    # 検証
    assert next_app.called
    assert next_app.received == LIMIT - 1


def test_call_when_content_length_over() -> None:
    """Content-Length が上限以上なら読まずに 413（異常系）。"""
    # 準備
    next_app = _NextApp()

    # 実行
    sent = _run(next_app, _scope(WEB_PATH, LIMIT), [LIMIT])

    # 検証
    assert not next_app.called
    assert sent[0]["status"] == 413
    assert dict(sent[0]["headers"])[b"content-type"].startswith(b"application/problem+json")


def test_call_when_chunked_over() -> None:
    """chunked で上限に達したら送出する（異常系）。"""
    from voice_paste.shared.errors import RequestBodyTooLargeError

    # 準備
    next_app = _NextApp()

    # 実行・検証
    with pytest.raises(RequestBodyTooLargeError):
        _run(next_app, _scope(WEB_PATH, None), [LIMIT // 2, LIMIT // 2])
    assert next_app.received == LIMIT // 2


def test_call_when_other_path() -> None:
    """対象外のパスは数えない（正常系）。"""
    # 準備
    next_app = _NextApp()

    # 実行
    _run(next_app, _scope("/sessions", LIMIT * 2), [10])

    # 検証
    assert next_app.called
    assert next_app.received == 10
