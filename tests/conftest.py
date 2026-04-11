"""pytest 共通フィクスチャ定義。"""

import pytest
from unittest.mock import patch

from tests.mocks.mock_env import MOCK_ENV


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """全テストに環境変数モックを適用する。"""
    for key, value in MOCK_ENV.items():
        monkeypatch.setenv(key, value)
