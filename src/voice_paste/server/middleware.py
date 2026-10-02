"""全ての要求で Host・Origin・トークンを確かめ、当たらなければ 403・401 で断る。"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from pydantic import SecretStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from voice_paste.server.error_handlers import problem_response

logger = logging.getLogger(__name__)

LOOPBACK_HOST_NAMES: tuple[str, ...] = ("127.0.0.1", "localhost")
"""Host に許す名前（ポートを付けて照合する）。"""

BEARER_PREFIX: str = "Bearer "
"""Authorization のトークンの前に付く語。"""


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Origin・Host・Authorization の順に確かめ、通れば次の処理へ渡す。"""

    def __init__(self, app: ASGIApp, token: SecretStr, port: int) -> None:
        """今回の起動のトークンと、待ち受けのポートを受ける。"""
        super().__init__(app)
        self._token = token
        self._port = port

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """要求を確かめ、断るなら problem+json の応答を、通るなら次の処理の応答を返す。"""
        origin = request.headers.get("origin")
        host = request.headers.get("host")

        # 1. Origin が付いていれば断る（ブラウザからの要求）
        if origin is not None:
            return self._reject(HTTPStatus.FORBIDDEN, "Origin が付いている", host, origin)

        # 2. Host が 127.0.0.1 か localhost のこの待ち受けのポートでなければ断る（DNS リバインディング）
        allowed_hosts = {f"{name}:{self._port}" for name in LOOPBACK_HOST_NAMES}
        if host not in allowed_hosts:
            return self._reject(HTTPStatus.FORBIDDEN, "Host が合わない", host, origin)

        # 3. Authorization がトークンと定数時間で一致しなければ断る
        expected = f"{BEARER_PREFIX}{self._token.get_secret_value()}"
        presented = request.headers.get("authorization", "")
        if not hmac.compare_digest(presented.encode(), expected.encode()):
            return self._reject(HTTPStatus.UNAUTHORIZED, "トークンが合わない", host, origin)

        # 4. 通すので次の処理へ渡す
        return await call_next(request)

    @staticmethod
    def _reject(status: HTTPStatus, reason: str, host: str | None, origin: str | None) -> Response:
        """断った理由をログに書いて、problem+json の応答を返す（トークンは書かない）。"""
        logger.warning(f"断った要求（{reason}・Host: {host}・Origin: {origin}）")
        return problem_response(status, reason)
