"""結合テストの共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import Stack, build_stack, stop_stack


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    """本物の app を空きポートに立て、偽物のマイク・音量・エンジンと返送先の受け口を差した一式を返す。"""
    built = build_stack(tmp_path)
    yield built
    stop_stack(built)
