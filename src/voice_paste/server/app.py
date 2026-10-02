"""セッションの route・要求の守り・例外ハンドラを組み込んだ FastAPI の app を組み立てる。"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import SecretStr

from voice_paste.features.session import SessionApiDeps, router
from voice_paste.server.error_handlers import register_exception_handlers
from voice_paste.server.middleware import RequestGuardMiddleware


def build_fastapi(session_api: SessionApiDeps, token: SecretStr, port: int) -> FastAPI:
    """文書のページを持たない app に、セッションの route・例外ハンドラ・要求の守りを組み込んで返す。"""
    # 1. 自動で作られる文書のページ（docs・redoc・openapi.json）を持たない app を作る
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    # 2. セッションの API の依存を置き、セッションの route を集める
    app.state.session_api = session_api
    app.include_router(router)

    # 3. 例外ハンドラを登録する
    register_exception_handlers(app)

    # 4. 要求の守りをトークンとポートつきで組み込む
    app.add_middleware(RequestGuardMiddleware, token=token, port=port)
    return app
