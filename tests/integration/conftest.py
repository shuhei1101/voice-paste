"""結合テストの共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import (
    OutputStack,
    Stack,
    build_output_stack,
    build_stack,
    stop_stack,
)
from voice_paste.shared.settings import Settings


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    """本物の app を空きポートに立て、偽物のマイク・音量・エンジンと返送先の受け口を差した一式を返す。"""
    built = build_stack(tmp_path)
    yield built
    stop_stack(built)


@pytest.fixture
def output_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[Settings | None], OutputStack]]:
    """設定を受けて、配線した出力先へ届く一式を作る関数を返す。テストの後に残ったセッションの録音を捨てる。"""
    built: list[OutputStack] = []

    def _build(settings: Settings | None = None) -> OutputStack:
        """設定（無ければ既定）で一式を作り、後片付けの対象に覚える。"""
        stack = build_output_stack(tmp_path, monkeypatch, settings)
        built.append(stack)
        return stack

    yield _build
    for stack in built:
        stack.manager.close()
