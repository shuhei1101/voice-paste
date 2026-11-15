"""外の端末のブラウザで開く画面（`GET /web/`）と、画面が読む素材（`/web/assets/`）の配信。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

WEB_DIR: Path = Path(__file__).parent / "web"
"""画面の HTML と素材をパッケージに同梱した場所。"""

WEB_PAGE_FILE: str = "index.html"
"""画面の HTML のファイル名。"""

WEB_ASSETS_DIR_NAME: str = "assets"
"""画面が読む JS・CSS を置くフォルダの名前（`/web/assets/` に組み込む）。"""

JS_MEDIA_TYPE: str = "text/javascript; charset=utf-8"
"""`/web/assets/` の下の `.js` の Content-Type。端末の `mimetypes`（Windows ではレジストリの値）に依らず RFC 9239 の型にする。"""

web_page_router = APIRouter()


@web_page_router.get("/web/")
def serve_web_page() -> FileResponse:
    """同梱した画面の HTML を、キャッシュさせずに返す。"""
    return FileResponse(
        WEB_DIR / WEB_PAGE_FILE,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@web_page_router.get("/web")
def redirect_web_page() -> RedirectResponse:
    """末尾の `/` が無い `/web` を `/web/` へ移す。"""
    return RedirectResponse("/web/", status_code=307)


class WebAssetFiles(StaticFiles):
    """`.js` の Content-Type を JS_MEDIA_TYPE に固定する StaticFiles。"""

    def file_response(
        self,
        full_path: os.PathLike[str] | str,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """StaticFiles の応答のうち、`.js` で Content-Type を持つもの（304 は持たない）の Content-Type を JS_MEDIA_TYPE に変更する。"""
        response = super().file_response(full_path, stat_result, scope, status_code)
        if Path(full_path).suffix == ".js" and "content-type" in response.headers:
            response.headers["content-type"] = JS_MEDIA_TYPE
        return response


def mount_web_assets(app: FastAPI) -> None:
    """`/web/assets` に同梱した素材を組み込む（`.js` は JS_MEDIA_TYPE で返却する。置き場所の外を指す `..` と無いファイルは StaticFiles が 404 にする）。"""
    app.mount(
        "/web/assets",
        WebAssetFiles(directory=WEB_DIR / WEB_ASSETS_DIR_NAME),
        name="web_assets",
    )
