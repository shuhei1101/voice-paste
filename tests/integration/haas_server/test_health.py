"""準備できたかを返す（GET /health）の結合テスト。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.haas_server.helpers import MODEL_NAME


def test_normal(client: TestClient) -> None:
    """モデルを読み込んだ後に呼ぶと、ok とモデルの名前を返す（正常系）。"""
    # 実行
    response = client.get("/health")

    # 検証
    assert response.status_code == 200
    assert response.json() == {"ok": True, "model": MODEL_NAME}


def test_error_when_origin_not_allowed(client: TestClient) -> None:
    """Origin が付いた要求を断る（異常系）。"""
    # 実行
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert MODEL_NAME not in response.text
