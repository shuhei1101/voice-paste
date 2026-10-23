"""全ての要求で Host を確かめ、`/web/` の外は Origin・トークンを、`/web/` の下は Origin の許可リストを確かめ、当たらなければ 403・401 で断る。"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable, Sequence
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


WEB_PATH_PREFIX: str = "/web"
"""外の端末のブラウザ向けの route の頭（`/web` と `/web/` の下）。"""

SAFE_METHODS: tuple[str, ...] = ("GET", "HEAD")
"""画面と同じオリジンの要求では Origin が付かないメソッド。"""


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Host を確かめ、`/web/` の下は Origin の許可リストを、それ以外は Origin とトークンを確かめて、通れば次の処理へ渡す。"""

    def __init__(
        self, app: ASGIApp, token: SecretStr, port: int, allowed_web_origins: Sequence[str]
    ) -> None:
        """今回の起動のトークンと、待ち受けのポートと、`/web/` の下に許す Origin を受ける。"""
        super().__init__(app)
        self._token = token
        self._port = port
        self._allowed_web_origins = frozenset(origin.rstrip("/") for origin in allowed_web_origins)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """要求を確かめ、断るなら problem+json の応答を、通るなら次の処理の応答を返す。"""
        origin = request.headers.get("origin")
        host = request.headers.get("host")

        # 1. Host が 127.0.0.1 か localhost のこの待ち受けのポートでなければ断る（DNS リバインディング）
        allowed_hosts = {f"{name}:{self._port}" for name in LOOPBACK_HOST_NAMES}
        if host not in allowed_hosts:
            return self._reject(HTTPStatus.FORBIDDEN, "Host が合わない", host, origin)

        # 2. /web/ の下か
        path = request.url.path
        if path == WEB_PATH_PREFIX or path.startswith(f"{WEB_PATH_PREFIX}/"):
            # 下: トークンは求めず、Origin の許可リストで通す
            return await self._guard_web(request, call_next, host, origin)

        # 3. 外: Origin が付いていれば断る（ブラウザからの要求）
        if origin is not None:
            return self._reject(HTTPStatus.FORBIDDEN, "Origin が付いている", host, origin)

        # 4. Authorization がトークンと定数時間で一致しなければ断る
        expected = f"{BEARER_PREFIX}{self._token.get_secret_value()}"
        presented = request.headers.get("authorization", "")
        if not hmac.compare_digest(presented.encode(), expected.encode()):
            return self._reject(HTTPStatus.UNAUTHORIZED, "トークンが合わない", host, origin)

        # 5. 通すので次の処理へ渡す
        return await call_next(request)

    async def _guard_web(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        host: str | None,
        origin: str | None,
    ) -> Response:
        """`/web/` の下の要求を Origin の許可リストで確かめ、通れば次の処理へ渡す。"""
        # GET・HEAD は画面と同じオリジンなら Origin が付かないため、Origin が無い要求も通す
        if request.method in SAFE_METHODS and origin is None:
            return await call_next(request)

        # 許す Origin が付いていれば通す
        if origin is not None and origin in self._allowed_web_origins:
            return await call_next(request)

        # どちらでもなければ断る（Origin が無い POST・ほかのオリジン）
        return self._reject(HTTPStatus.FORBIDDEN, "Origin が許されていない", host, origin)

    @staticmethod
    def _reject(status: HTTPStatus, reason: str, host: str | None, origin: str | None) -> Response:
        """断った理由をログに書いて、problem+json の応答を返す（トークンは書かない）。"""
        logger.warning(f"断った要求（{reason}・Host: {host}・Origin: {origin}）")
        return problem_response(status, reason)
