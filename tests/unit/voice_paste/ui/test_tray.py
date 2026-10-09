"""ui/tray.py（Tray の set_state・set_failed・show_failure・set_recording_window・アイコンの左クリック）の単体テスト。

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


# === set_recording_window ===


def test_set_recording_window_when_hidden(qapp: QApplication, tmp_path: Path) -> None:
    """隠している間は項目を押せ、太字にする（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState, TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_state(TrayState.RECORDING, busy=True)

    # 実行
    tray.set_recording_window(RecordingWindowState.HIDDEN)

    # 検証
    show = _menu_action(tray, "録音の画面を出す")
    start = _menu_action(tray, "録音を始める（処理中）")
    assert show.isEnabled()
    assert show.font().bold()
    assert not start.font().bold()


def test_set_recording_window_when_shown(qapp: QApplication, tmp_path: Path) -> None:
    """画面が出ている間は理由を添えて押せなくする（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_recording_window(RecordingWindowState.SHOWN)

    # 検証
    show = _menu_action(tray, "録音の画面を出す（表示中）")
    assert not show.isEnabled()
    assert not show.font().bold()


def test_set_recording_window_when_no_window(qapp: QApplication, tmp_path: Path) -> None:
    """画面を出さない録音では理由を添えて押せなくする（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_recording_window(RecordingWindowState.NO_WINDOW)

    # 検証
    show = _menu_action(tray, "録音の画面を出す（画面を出さない録音）")
    assert not show.isEnabled()
    assert not show.font().bold()


def test_set_recording_window_when_not_recording(qapp: QApplication, tmp_path: Path) -> None:
    """録音していないときは理由を添えて押せなくする（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_recording_window(RecordingWindowState.NOT_RECORDING)

    # 検証
    show = _menu_action(tray, "録音の画面を出す（録音していません）")
    assert not show.isEnabled()
    assert not show.font().bold()


# === アイコンの左クリック ===


def test_icon_click_when_window_hidden(qapp: QApplication, tmp_path: Path) -> None:
    """隠している間のアイコンの左クリックは、録音の画面を戻す知らせを出す（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState, TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_state(TrayState.RECORDING, busy=True)
    tray.set_recording_window(RecordingWindowState.HIDDEN)
    show_requested = MagicMock()
    start_requested = MagicMock()
    tray.show_window_requested.connect(show_requested)
    tray.start_requested.connect(start_requested)

    # 実行
    tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    # 検証
    show_requested.assert_called_once()
    start_requested.assert_not_called()


def test_icon_click_when_window_shown(qapp: QApplication, tmp_path: Path) -> None:
    """録音の画面が出ている間のアイコンの左クリックは何もしない（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState, TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_state(TrayState.RECORDING, busy=True)
    tray.set_recording_window(RecordingWindowState.SHOWN)
    show_requested = MagicMock()
    start_requested = MagicMock()
    tray.show_window_requested.connect(show_requested)
    tray.start_requested.connect(start_requested)

    # 実行
    tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    # 検証
    show_requested.assert_not_called()
    start_requested.assert_not_called()
