"""セッションとブラウザの文字起こしの route・画面の配信・要求の守り・本文の上限・例外ハンドラを組み込んだ FastAPI の app を組み立てる。"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from pydantic import SecretStr

from voice_paste.features.session import SessionApiDeps, router
from voice_paste.features.web_transcription import WebApiDeps
from voice_paste.features.web_transcription import router as web_router
from voice_paste.server.body_limit import BodyLimitMiddleware
from voice_paste.server.error_handlers import register_exception_handlers
from voice_paste.server.middleware import RequestGuardMiddleware
from voice_paste.server.web_page import mount_web_assets, web_page_router


def build_fastapi(
    session_api: SessionApiDeps,
    token: SecretStr,
    port: int,
    *,
    web_api: WebApiDeps,
    allowed_web_origins: Sequence[str],
) -> FastAPI:
    """文書のページを持たない app に、route・画面の配信・例外ハンドラ・本文の上限・要求の守りを組み込んで返す。"""
    # 1. 自動で作られる文書のページ（docs・redoc・openapi.json）を持たない app を作る
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    # 2. セッションの API の依存を置き、セッションの route を集める
    app.state.session_api = session_api
    app.include_router(router)

    # 3. ブラウザの API の依存を置き、ブラウザの文字起こしの route と画面の配信を集めて、画面の素材を組み込む
    app.state.web_api = web_api
    app.include_router(web_router)
    app.include_router(web_page_router)
    mount_web_assets(app)

    # 4. 例外ハンドラを登録する
    register_exception_handlers(app)

    # 5. 本文の上限を組み込む
    app.add_middleware(BodyLimitMiddleware)

    # 6. 要求の守りをトークン・ポート・許す Origin つきで組み込む（最後に追加するため、本文の上限より先に動き、断る要求の本文を読まない）
    app.add_middleware(
        RequestGuardMiddleware,
        token=token,
        port=port,
        allowed_web_origins=allowed_web_origins,
    )
    return app
