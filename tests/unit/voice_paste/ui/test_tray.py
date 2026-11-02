"""ui/tray.py（Tray の __init__・set_state・set_failed・show_failure・show_copy_completed・通知の押下・set_recording_window・アイコンの左クリック）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
メニューの項目は、表示の文言の先頭で引く（右に出すホットキーは文言の後ろに付く）。
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
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


# === __init__ ===


def test_init_shows_icon_before_tooltip(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ヒントを付けずにアイコンを出し、出した後に準備中のヒントを付ける（正常系）。"""
    # 準備
    shown: list[tuple[str, bool]] = []

    def record_show(icon: QSystemTrayIcon) -> None:
        shown.append((icon.toolTip(), not icon.icon().isNull()))

    monkeypatch.setattr(QSystemTrayIcon, "show", record_show)

    # 実行
    tray = make_tray(tmp_path)

    # 検証
    assert shown == [("", True)]
    assert tray._icon.toolTip() == "voice-paste: 準備中"


# === set_state ===


def test_set_state_when_starting(qapp: QApplication, tmp_path: Path) -> None:
    """準備中は録音と設定を押せず、再起動と終了は押せる（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_state(TrayState.STARTING, busy=False)

    # 検証
    assert not _menu_action(tray, "録音を開始").isEnabled()
    assert not _menu_action(tray, "設定…").isEnabled()
    assert _menu_action(tray, "再起動").isEnabled()
    assert _menu_action(tray, "終了").isEnabled()
    assert tray._icon.toolTip() == "voice-paste: 準備中"


def test_set_state_when_busy(qapp: QApplication, tmp_path: Path) -> None:
    """処理中は録音と設定を押せなくする（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)

    # 実行
    tray.set_state(TrayState.TRANSCRIBING, busy=True)

    # 検証
    start = _menu_action(tray, "録音を開始（処理中）")
    settings = _menu_action(tray, "設定…（処理中）")
    assert not start.isEnabled()
    assert not settings.isEnabled()
    assert not start.font().bold()
    assert tray._icon.toolTip() == "voice-paste: 文字起こし中"


def test_set_state_when_failed(qapp: QApplication, tmp_path: Path) -> None:
    """エンジンを準備できなかった起動では設定だけ押せる（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_failed(settings_enabled=True)

    # 実行
    tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    start = _menu_action(tray, "録音を開始（準備に失敗）")
    settings = _menu_action(tray, "設定…")
    assert not start.isEnabled()
    assert settings.isEnabled()
    assert tray._icon.toolTip() == "voice-paste: 失敗"


def test_set_state_when_failed_without_settings(qapp: QApplication, tmp_path: Path) -> None:
    """設定を読めなかった起動では録音も設定も押せない（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    tray = make_tray(tmp_path)
    tray.set_failed(settings_enabled=False)

    # 実行
    tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    start = _menu_action(tray, "録音を開始（準備に失敗）")
    settings = _menu_action(tray, "設定…")
    restart = _menu_action(tray, "再起動")
    assert not start.isEnabled()
    assert not settings.isEnabled()
    assert restart.isEnabled()
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
        "文字起こしできませんでした",
        "録音を読めませんでした。録音は履歴に残っています。",
    )


@pytest.mark.parametrize(
    ("paths", "shown_paths"),
    [
        pytest.param(
            (PureWindowsPath("C:/a/settings.yaml"),), "C:\\a\\settings.yaml", id="one_file"
        ),
        pytest.param(
            (PureWindowsPath("C:/a/settings.yaml"), PureWindowsPath("C:/r/settings.local.yaml")),
            "C:\\a\\settings.yaml・C:\\r\\settings.local.yaml",
            id="two_files",
        ),
    ],
)
def test_show_failure_when_settings_invalid(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths: tuple[PureWindowsPath, ...],
    shown_paths: str,
) -> None:
    """設定を読めないときは、読めなかったファイルのパスを本文に出す（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)

    # 実行
    tray.show_failure("settings_invalid", "理由", paths=paths)

    # 検証
    show_message.assert_called_once()
    assert show_message.call_args.args[:2] == (
        "起動できませんでした",
        f"設定ファイルを読み込めませんでした（理由）。{shown_paths} を修正して再起動してください。",
    )


def test_show_failure_when_paste_unavailable(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """貼り付けを使えないことを権限の設定の手順と共に通知する（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)

    # 実行
    tray.show_failure("paste_unavailable", "Permission denied")

    # 検証
    show_message.assert_called_once()
    assert show_message.call_args.args[:2] == (
        "貼り付けを使用できません",
        "貼り付けのキーを送信できません（Permission denied）。/dev/uinput の権限を設定して PC を再起動してください（使い方「起動と設定」）。「コピーのみ」は使えます。",
    )


# === show_copy_completed ===


def test_show_copy_completed(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コピーの完了の文言で情報の通知を出す（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)

    # 実行
    tray.show_copy_completed("テスト")

    # 検証
    show_message.assert_called_once()
    assert show_message.call_args.args[:3] == (
        "コピーしました",
        "任意の場所に貼り付けてください。この通知を押すと、もう一度コピーします。",
        QSystemTrayIcon.MessageIcon.Information,
    )


# === _on_message_clicked ===


def test_on_message_clicked_when_copy_completed(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コピーの完了の通知を押すとコピーし直しを頼む（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", MagicMock())
    open_url = MagicMock()
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    recopy_requested = MagicMock()
    tray.recopy_requested.connect(recopy_requested)
    tray.show_copy_completed("テスト")

    # 実行
    tray._icon.messageClicked.emit()

    # 検証
    recopy_requested.assert_called_once_with("テスト")
    open_url.assert_not_called()


def test_on_message_clicked_when_failure_after_copy(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コピーの完了の後に出した失敗の通知を押すとログフォルダを開く（正常系）。"""
    # 準備
    tray = make_tray(tmp_path)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", MagicMock())
    open_url = MagicMock()
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    recopy_requested = MagicMock()
    tray.recopy_requested.connect(recopy_requested)
    tray.show_copy_completed("テスト")
    tray.show_failure("delivery_failed", "理由")

    # 実行
    tray._icon.messageClicked.emit()

    # 検証
    open_url.assert_called_once_with(QUrl.fromLocalFile(str(tmp_path / "log")))
    recopy_requested.assert_not_called()


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
    show = _menu_action(tray, "録音の画面を表示")
    start = _menu_action(tray, "録音を開始（処理中）")
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
    show = _menu_action(tray, "録音の画面を表示（表示中）")
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
    show = _menu_action(tray, "録音の画面を表示（画面を表示しない録音）")
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
    show = _menu_action(tray, "録音の画面を表示（録音していません）")
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
