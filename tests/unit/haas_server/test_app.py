"""haas_server/app.py（create_app）の単体テスト。API の流れは結合テスト（tests/integration/haas_server/）が持つ。"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

PORT = 47824


def test_create_app_when_host_not_allowed() -> None:
    """Host が合わない要求を断る（異常系）。"""
    from haas_server.app import HaasEngine, create_app

    # 準備
    engine = HaasEngine(
        model_name="m",
        transcribe=MagicMock(return_value="文字"),
        transcribe_longform=MagicMock(return_value="文字"),
        build_vocabulary=MagicMock(),
    )
    client = TestClient(create_app(engine, port=PORT, request_shutdown=MagicMock()))

    # 実行
    response = client.get("/health", headers={"Host": f"evil.example:{PORT}"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
