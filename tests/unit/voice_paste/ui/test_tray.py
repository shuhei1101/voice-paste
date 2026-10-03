"""ui/tray.py（Tray の set_state・set_failed・show_failure）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
メニューの項目は、表示の文言の先頭で引く（右に出すホットキーは文言の後ろに付く）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon

from tests.unit.voice_paste.ui.helpers import make_tray

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.ui.tray import Tray


def _menu_action(tray: Tray, label: str) -> QAction:
    """トレイのメニューから、表示の文言が label で始まる項目を返す（右のホットキーは `\\t` の後ろに付く）。"""
    actions = [
        action
        for action in tray._icon.contextMenu().actions()
        if action.text().split("\t")[0] == label
    ]
    assert len(actions) == 1, f"{label} の項目が 1 つでない: {actions}"
    return actions[0]


# === set_state ===


def test_set_state_when_busy(qapp: QApplication, tmp_path: Path) -> None:
    """処理中は録音と設定を押せなくする（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_state(TrayState.TRANSCRIBING, busy=True)

    # 検証
    start = _menu_action(tray, "録音を始める（処理中）")
    settings = _menu_action(tray, "設定…（処理中）")
    assert not start.isEnabled()
    assert not settings.isEnabled()
    assert not start.font().bold()
    assert tray._icon.toolTip() == "voice-paste: 文字起こし中"


def test_set_state_when_failed(qapp: QApplication, tmp_path: Path) -> None:
    """失敗の起動では設定だけ押せる（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_failed()

    # 実行
    tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    start = _menu_action(tray, "録音を始める（準備に失敗）")
    settings = _menu_action(tray, "設定…")
    assert not start.isEnabled()
    assert settings.isEnabled()
    assert tray._icon.toolTip() == "voice-paste: 失敗"


# === show_failure ===


def test_show_failure(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """種類ごとの文言で通知する（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)

    # 実行
    tray.show_failure("transcription_failed", "録音を読めませんでした")

    # 検証
    show_message.assert_called_once()
    assert show_message.call_args.args[:2] == (
        "文字起こしに失敗しました",
        "録音を読めませんでした。録音は履歴に残っています。",
    )
