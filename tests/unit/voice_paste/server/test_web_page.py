"""server/web_page.py（serve_web_page・mount_web_assets）の単体テスト。

build_fastapi が組み込んだ画面の配信を、TestClient（base_url は 127.0.0.1:{ポート}）で確かめる。
"""

from __future__ import annotations

from pathlib import Path

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
    assert asset.headers["content-type"].startswith("text/javascript")
    assert outside.status_code == 404
    assert outside.headers["content-type"].startswith("application/problem+json")
