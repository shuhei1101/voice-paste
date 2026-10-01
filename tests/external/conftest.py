"""外部疎通テストのガード。`--run-external` が無ければ、このフォルダのテストは全て skip する。"""

from __future__ import annotations

from pathlib import Path

import pytest

RUN_EXTERNAL_OPTION: str = "--run-external"
"""外部疎通テストを実行するためのオプション。"""

EXTERNAL_TESTS_DIR: Path = Path(__file__).parent
"""外部疎通テストを置くフォルダ。"""


def pytest_addoption(parser: pytest.Parser) -> None:
    """外部疎通テストを実行するオプションを足す。"""
    parser.addoption(
        RUN_EXTERNAL_OPTION,
        action="store_true",
        default=False,
        help="実際の外部サービスへ接続する外部疎通テストを実行する（従量課金がかかる）",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """オプションが無ければ、このフォルダのテストを skip にする（ほかのフォルダのテストは変えない）。"""
    if config.getoption(RUN_EXTERNAL_OPTION, default=False):
        return
    skip_marker = pytest.mark.skip(reason=f"{RUN_EXTERNAL_OPTION} が無いため外部疎通テストは実行しない")
    for item in items:
        # このフォルダの下のテストだけに付ける
        if Path(str(item.fspath)).is_relative_to(EXTERNAL_TESTS_DIR):
            item.add_marker(skip_marker)
