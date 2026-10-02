"""server/app.py（build_fastapi）の単体テスト。

SessionManager は Mock にして、TestClient（base_url は 127.0.0.1:{ポート}）で要求の守りを通した先を確かめる。
"""

from __future__ import annotations

import pytest

from tests.unit.voice_paste.server.helpers import AUTHORIZATION, CALLBACK_URL, make_client


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
    session_manager.start.assert_called_once_with(entry="api", callback_url=CALLBACK_URL)


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_build_fastapi_when_docs_requested(path: str) -> None:
    """文書のページを出さない（正常系）。"""
    # 準備
    client, _session_manager = make_client()

    # 実行
    response = client.get(path, headers=AUTHORIZATION)

    # 検証
    assert response.status_code == 404
