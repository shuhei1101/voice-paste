"""pytest 共通フィクスチャ定義。"""

import pytest
from unittest.mock import patch

from tests.mocks.mock_env import MOCK_ENV


RUN_E2E_OPTION: str = "--run-e2e"
"""実機のマイク・システム音量・GPU を使うテストを実行するためのオプション。"""

REAL_MACHINE_MARKER: str = "real_machine"
"""実機を使うテストに付けるマーカー（`--run-e2e` が無ければ skip する）。"""


def pytest_addoption(parser: pytest.Parser) -> None:
    """実機のテストを実行するオプションを足す。"""
    parser.addoption(
        RUN_E2E_OPTION,
        action="store_true",
        default=False,
        help="実機のマイク・システム音量・GPU を使うテスト（E2E・実機の非機能要件テスト）を実行する",
    )


def pytest_configure(config: pytest.Config) -> None:
    """実機のテストのマーカーを登録する。"""
    config.addinivalue_line(
        "markers",
        f"{REAL_MACHINE_MARKER}: 実機のマイク・システム音量・GPU を使う（{RUN_E2E_OPTION} が要る）",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """オプションが無ければ、実機のテストを skip にする。"""
    if config.getoption(RUN_E2E_OPTION, default=False):
        return
    skip_marker = pytest.mark.skip(reason=f"{RUN_E2E_OPTION} が無いため実機のテストは実行しない")
    for item in items:
        if item.get_closest_marker(REAL_MACHINE_MARKER) is not None:
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """全テストに環境変数モックを適用する。"""
    for key, value in MOCK_ENV.items():
        monkeypatch.setenv(key, value)
