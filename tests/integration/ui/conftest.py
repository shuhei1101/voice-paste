"""画面の結合テストの共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QWindow

from tests.integration.ui.helpers import Ui, build_ui

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings


@pytest.fixture
def make_ui(qapp: QApplication, tmp_path: Path) -> Iterator[Callable[..., Ui]]:
    """設定（無ければ既定）で本物のトレイ・窓をつないだ一式を作る関数を返す。テストの後に窓とトレイを片付ける。"""
    built: list[Ui] = []

    def _make(settings: Settings | None = None, **deps_overrides: object) -> Ui:
        """一式を作り、後片付けの対象に覚える。"""
        ui = build_ui(tmp_path, settings, **deps_overrides)
        built.append(ui)
        return ui

    yield _make
    for ui in built:
        ui.close()


@pytest.fixture
def system_move(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QWindow.startSystemMove を、OS に窓の移動を任せず呼ばれたことだけを控える偽物に替える。"""
    start_system_move = MagicMock(return_value=True)
    monkeypatch.setattr(QWindow, "startSystemMove", start_system_move)
    return start_system_move
