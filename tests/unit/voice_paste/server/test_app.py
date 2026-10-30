"""server/app.py（build_fastapi）の単体テスト。

SessionManager は Mock にして、TestClient（base_url は 127.0.0.1:{ポート}）で要求の守りを通した先を確かめる。
"""

from __future__ import annotations

import pytest

from tests.unit.voice_paste.server.helpers import (
    AUTHORIZATION,
    CALLBACK_URL,
    make_client,
    make_client_without_web,
)


def test_build_fastapi() -> None:
    """守りを通った開始がセッション管理へ届く（正常系）。"""
    # 準備
    client, session_manager = make_client()

    # 実行
    response = client.post(
        "/sessions", json={"callback_url": CALLBACK_URL}, headers=AUTHORIZATION
    )

    # 検証
    assert response.status_code == 202
    assert response.json() == {"session_id": "session-1"}
    session_manager.start.assert_called_once_with(
        entry="api", callback_url=CALLBACK_URL, continuous=False, glossary_preset=None
    )


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_build_fastapi_when_docs_requested(path: str) -> None:
    """文書のページを出さない（正常系）。"""
    # 準備
    client, _session_manager = make_client()

    # 実行
    response = client.get(path, headers=AUTHORIZATION)

    # 検証
    assert response.status_code == 404


def test_build_fastapi_when_web_disabled() -> None:
    """web_api が None ならブラウザの画面と API を持たない（正常系）。"""
    # 準備
    client, _session_manager = make_client_without_web()

    # 実行
    page = client.get("/web/")
    page_with_origin = client.get("/web/", headers={"Origin": "http://evil.example"})
    upload = client.post("/web/transcriptions")

    # 検証
    assert page.status_code == 404
    assert page_with_origin.status_code == 404
    assert upload.status_code == 404
