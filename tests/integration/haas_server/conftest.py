"""Haas の文字起こしのサーバーの結合テストのフィクスチャ。"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from haas_server.app import create_app
from tests.integration.haas_server.helpers import FakeModel

PORT = 47824


@pytest.fixture
def model() -> FakeModel:
    """Haas のモデルの代わりを返す。"""
    return FakeModel()


@pytest.fixture
def client(model: FakeModel) -> Iterator[TestClient]:
    """偽のモデルを持つ app へ、許された Host で接続するクライアントを返す。"""
    app = create_app(model.engine(), port=PORT, request_shutdown=MagicMock())
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as test_client:
        yield test_client
