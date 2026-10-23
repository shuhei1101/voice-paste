"""画面の結合テストの共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QWindow

from tests.integration.ui.helpers import (
    Ui,
    build_ui,
    dispose_windows_since,
    flush_deletions,
    top_level_windows,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings


@pytest.fixture(autouse=True)
def no_leftover_windows(qapp: QApplication) -> Iterator[None]:
    """テストの後に、そのテストの前に無かったトップレベルの窓が残っていれば、窓の名前を出して失敗させる。

    残った窓は破棄してから失敗させ、後のテストへ持ち越さない。他のフィクスチャの片付けの後に確かめるため、最初に作る。
    """
    before = top_level_windows()
    yield
    flush_deletions()
    left = top_level_windows() - before
    names = [f"{type(window).__name__}({window.objectName()})" for window in left]
    dispose_windows_since(before)
    assert not names, f"テストの後に窓が残った: {', '.join(names)}"


@pytest.fixture
def make_ui(qapp: QApplication, tmp_path: Path) -> Iterator[Callable[..., Ui]]:
    """設定（無ければ既定）で本物のトレイ・窓をつないだ一式を作る関数を返す。テストの後に窓とトレイを片付ける。"""
    before = top_level_windows()
    built: list[Ui] = []

    def _make(settings: Settings | None = None, **deps_overrides: object) -> Ui:
        """一式を作り、後片付けの対象に覚える。"""
        ui = build_ui(tmp_path, settings, **deps_overrides)
        built.append(ui)
        return ui

    yield _make
    for ui in built:
        ui.close()
    # 一式が開いた設定画面・メニューなど、テストの前に無かった窓も破棄する
    dispose_windows_since(before)


@pytest.fixture
def system_move(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QWindow.startSystemMove を、OS に窓の移動を任せず呼ばれたことだけを控える偽物に替える。"""
    start_system_move = MagicMock(return_value=True)
    monkeypatch.setattr(QWindow, "startSystemMove", start_system_move)
    return start_system_move


@pytest.fixture
def apply_theme_to_app(qapp: QApplication, tmp_path: Path) -> Iterator[Callable[[str], None]]:
    """ui.theme を QApplication に当てる関数を返す。テストの後にスタイルシートと Qt の明暗の上書きを外す。"""
    from voice_paste.ui.style import apply_theme

    def _apply(theme: str) -> None:
        """ui.theme の値で明暗を当てる。"""
        apply_theme(qapp, theme, image_dir=tmp_path / "ui")

    yield _apply
    qapp.setStyleSheet("")
    qapp.styleHints().unsetColorScheme()
