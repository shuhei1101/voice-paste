"""server/web_page.py（serve_web_page・mount_web_assets・WebAssetFiles）の単体テスト。

build_fastapi が組み込んだ画面の配信を、TestClient（base_url は 127.0.0.1:{ポート}）で確かめる。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import pytest

from tests.unit.voice_paste.server.helpers import make_web_client


def test_serve_web_page(tmp_path: Path) -> None:
    """画面を返す（正常系）。"""
    # 準備
    client, _queue, _probe_audio = make_web_client(tmp_path)

    # 実行
    page = client.get("/web/", follow_redirects=False)
    moved = client.get("/web", follow_redirects=False)

    # 検証
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-cache"
    assert moved.status_code == 307
    assert moved.headers["location"].endswith("/web/")


def test_mount_web_assets(tmp_path: Path) -> None:
    """素材を返し、置き場所の外は 404（正常系）。"""
    # 準備
    client, _queue, _probe_audio = make_web_client(tmp_path)

    # 実行
    asset = client.get("/web/assets/app.js")
    outside = client.get("/web/assets/..%2F..%2Fapp.py")

    # 検証
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "text/javascript; charset=utf-8"
    assert outside.status_code == 404
    assert outside.headers["content-type"].startswith("application/problem+json")


def test_file_response_when_registry_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端末の mimetypes が別の型を返却しても、.js は JS_MEDIA_TYPE で返却する（正常系）。"""
    # 準備
    original_guess_type = mimetypes.guess_type

    def guess_type_like_runner(url: str, strict: bool = True) -> tuple[str | None, str | None]:
        """ランナーの Windows のレジストリと同じく .js に application/javascript を返却し、ほかは元の guess_type へ委ねる。"""
        if str(url).endswith(".js"):
            return "application/javascript", None
        return original_guess_type(url, strict)

    monkeypatch.setattr("starlette.responses.guess_type", guess_type_like_runner)
    client, _queue, _probe_audio = make_web_client(tmp_path)

    # 実行
    script = client.get("/web/assets/app.js")
    style = client.get("/web/assets/style.css")

    # 検証
    assert script.status_code == 200
    assert script.headers["content-type"] == "text/javascript; charset=utf-8"
    assert style.status_code == 200
    assert style.headers["content-type"].startswith("text/css")
