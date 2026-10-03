"""pytest 共通フィクスチャ定義。"""

import os
from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

# 画面を使うテストは、窓を実際には出さない offscreen のプラットフォームで動かす（QApplication を作る前に決める）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


@pytest.fixture(scope="session")
def qapp() -> "QApplication":
    """offscreen の QApplication を、テスト全体で 1 つだけ作って返す（最後の窓を閉じても終わらない）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app
