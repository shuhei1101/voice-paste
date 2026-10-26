"""`POST /web/transcriptions` の本文が上限以上なら 413 で断る。"""

from __future__ import annotations

import logging
from http import HTTPStatus

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from voice_paste.server.error_handlers import problem_response
from voice_paste.shared.errors import RequestBodyTooLargeError

logger = logging.getLogger(__name__)

WEB_BODY_LIMIT_BYTES: int = 100_000_000
"""`POST /web/transcriptions` の本文の上限（このバイト数以上を 413）。非機能要件のブラウザの本文の上限。画面の app.js も同じ値で送信前に確かめる。"""

LIMITED_METHOD: str = "POST"
"""本文の大きさを数える要求のメソッド。"""

LIMITED_PATH: str = "/web/transcriptions"
"""本文の大きさを数える要求のパス。"""


class BodyLimitMiddleware:
    """`POST /web/transcriptions` の本文を流しながら数え、上限以上なら断る純粋な ASGI middleware。

    BaseHTTPMiddleware は本文を流しながら数えられないため、ASGI の receive を包む。
    """

    def __init__(self, app: ASGIApp, limit: int = WEB_BODY_LIMIT_BYTES) -> None:
        """次の ASGI アプリと、本文の上限（このバイト数以上を断る）を受ける。"""
        self._app = app
        self._limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """対象の要求の本文の大きさを確かめながら次へ渡す。"""
        # 1. 対象の要求（http の POST /web/transcriptions）でなければそのまま次へ渡す
        if (
            scope["type"] != "http"
            or scope["method"] != LIMITED_METHOD
            or scope["path"] != LIMITED_PATH
        ):
            await self._app(scope, receive, send)
            return

        # 2. Content-Length があり上限以上なら、本文を読まずに 413 を返す
        content_length = self._content_length(scope)
        if content_length is not None and content_length >= self._limit:
            logger.warning(f"本文が大きすぎるため断った（{content_length} バイト）")
            response = problem_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "本文が大きすぎます")
            await response(scope, receive, send)
            return

        # 3. 本文を読むたびに大きさを足し、上限以上になったら送出する包んだ receive を次へ渡す
        received = 0
        exceeded = False
        replied = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                # Content-Length の無い本文が、読んでいる途中で上限に達した
                if received >= self._limit:
                    logger.warning(f"本文が大きすぎるため断った（{received} バイトで上限に達した）")
                    exceeded = True
                    raise RequestBodyTooLargeError("本文が大きすぎます")
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal replied
            # 上限に達する前は、次のアプリの応答をそのまま返す
            if not exceeded:
                await send(message)
                return
            # 上限に達した後: 次のアプリの応答（FastAPI が本文の解析の失敗として返す 400 など）は捨て、413 を 1 度だけ返す
            if not replied:
                replied = True
                response = problem_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "本文が大きすぎます")
                await response(scope, receive, send)

        await self._app(scope, counting_receive, guarded_send)

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        """Content-Length の値を返す。無い・数でないときは None。"""
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None
