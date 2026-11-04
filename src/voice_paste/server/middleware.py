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


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Host を確かめ、`/web/` の下は Origin の許可リストを、それ以外は Origin とトークンを確かめて、通れば次の処理へ渡す。"""

    def __init__(
        self,
        app: ASGIApp,
        token: SecretStr,
        port: int,
        allowed_web_origins: Sequence[str],
        web_enabled: bool,  # noqa: FBT001 starlette が add_middleware のキーワード引数で渡す
    ) -> None:
        """今回の起動のトークンと、待ち受けのポートと、`/web/` の下に許す Origin と、ブラウザの機能を組み込んだかを受ける。"""
        super().__init__(app)
        self._token = token
        self._port = port
        self._allowed_web_origins = frozenset(origin.rstrip("/") for origin in allowed_web_origins)
        self._web_enabled = web_enabled

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
            # 下でブラウザの機能を組み込んでいない: Origin もトークンも見ずに次へ渡す（route が無いため 404 になる）
            if not self._web_enabled:
                return await call_next(request)
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
        # Origin が無い要求（同じオリジンの GET・同じ端末のほかのプロセス）と、許す Origin が付いた要求はメソッドによらず通す
        if origin is None or origin in self._allowed_web_origins:
            return await call_next(request)

        # ほかのオリジンが付いていれば断る
        return self._reject(HTTPStatus.FORBIDDEN, "Origin が許されていない", host, origin)

    @staticmethod
    def _reject(status: HTTPStatus, reason: str, host: str | None, origin: str | None) -> Response:
        """断った理由をログに書いて、problem+json の応答を返す（トークンは書かない）。"""
        logger.warning(f"断った要求（{reason}・Host: {host}・Origin: {origin}）")
        return problem_response(status, reason)
