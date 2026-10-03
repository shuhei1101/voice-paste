"""ui/controller.py（UiController の on_notified・request_exit・open_settings）の単体テスト。

UiDeps の関数・トレイ・録音の画面・文字起こし中の表示は Mock に差し替える（設定画面だけは本物を開く）。
画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.unit.voice_paste.ui.helpers import make_session, make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings
    from voice_paste.ui.controller import UiController, UiDeps


@dataclass
class Parts:
    """UiController と、注入した偽物。"""

    controller: UiController
    deps: UiDeps
    tray: MagicMock
    recording_window: MagicMock
    indicator: MagicMock


def _make_controller(tmp_path: Path, *, settings: Settings | None = None) -> Parts:
    """UiDeps の関数・トレイ・録音の画面・文字起こし中の表示を Mock にした UiController を作る。"""
    from voice_paste.ui.controller import UiController

    deps = make_ui_deps(tmp_path, settings=settings)
    tray = MagicMock()
    recording_window = MagicMock()
    indicator = MagicMock()
    controller = UiController(
        deps, tray=tray, recording_window=recording_window, indicator=indicator
    )
    return Parts(
        controller=controller,
        deps=deps,
        tray=tray,
        recording_window=recording_window,
        indicator=indicator,
    )


# === on_notified ===


def test_on_notified_when_recording(qapp: QApplication, tmp_path: Path) -> None:
    """ホットキーの録音で録音の画面を出す（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = make_session("hotkey", "recording")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.tray.set_state.assert_called_once_with(TrayState.RECORDING, busy=True)
    parts.recording_window.open.assert_called_once()
    parts.indicator.close_window.assert_called_once()


def test_on_notified_when_hidden_window(qapp: QApplication, tmp_path: Path) -> None:
    """画面を出さない設定では録音の画面を出さない（正常系）。"""
    from voice_paste.shared.settings import RecordingSettings, Settings
    from voice_paste.ui.tray import TrayState

    # 準備
    parts = _make_controller(
        tmp_path, settings=Settings(recording=RecordingSettings(hide_window=True))
    )
    parts.deps.current_session.return_value = make_session("hotkey", "recording")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.tray.set_state.assert_called_once_with(TrayState.RECORDING, busy=True)
    parts.recording_window.open.assert_not_called()


def test_on_notified_when_api_session(qapp: QApplication, tmp_path: Path) -> None:
    """API の録音では画面を出さない（正常系）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = make_session("api", "transcribing")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.tray.set_state.assert_called_once_with(TrayState.TRANSCRIBING, busy=True)
    parts.indicator.open.assert_not_called()


def test_on_notified_when_idle_with_pending_quit(qapp: QApplication, tmp_path: Path) -> None:
    """待たせた終了を待機中で行う（正常系）。"""
    # 準備: 処理中に終了を頼み、待機中へ戻ったことを知らせる
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = make_session("hotkey", "transcribing")
    parts.controller.request_exit("quit")
    parts.deps.current_session.return_value = None

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.deps.request_quit.assert_called_once()


def test_on_notified_when_busy(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """処理中のダイアログを出す（正常系）。"""
    # 準備
    show_busy_dialog = MagicMock()
    monkeypatch.setattr("voice_paste.ui.controller.show_busy_dialog", show_busy_dialog)
    parts = _make_controller(tmp_path)

    # 実行
    parts.controller.on_notified("busy", None)

    # 検証
    show_busy_dialog.assert_called_once()


def test_on_notified_when_failure(qapp: QApplication, tmp_path: Path) -> None:
    """失敗をトレイの通知で知らせる（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)

    # 実行
    parts.controller.on_notified("delivery_failed", "クリップボードに書けない")

    # 検証
    parts.tray.show_failure.assert_called_once_with("delivery_failed", "クリップボードに書けない")


# === request_exit ===


def test_request_exit_when_idle(qapp: QApplication, tmp_path: Path) -> None:
    """待機中ならすぐ再起動する（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = None

    # 実行
    parts.controller.request_exit("restart")

    # 検証
    parts.deps.request_restart.assert_called_once()
    parts.tray.hide.assert_not_called()


def test_request_exit_when_busy(qapp: QApplication, tmp_path: Path) -> None:
    """処理中はアイコンを消して待たせる（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = make_session("hotkey", "transcribing")

    # 実行
    parts.controller.request_exit("quit")

    # 検証
    parts.tray.hide.assert_called_once()
    parts.deps.request_quit.assert_not_called()


# === open_settings ===


def test_open_settings(qapp: QApplication, tmp_path: Path) -> None:
    """開いている間はホットキーを止め、閉じると張り直す（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)

    # 実行: 開いた時点ではホットキーを止めただけで、取り消しで閉じると張り直す
    parts.controller.open_settings()
    suspended_when_open = parts.deps.suspend_hotkeys.call_count
    resumed_when_open = parts.deps.resume_hotkeys.call_count
    parts.controller._settings_window.try_close()

    # 検証
    assert suspended_when_open == 1
    assert resumed_when_open == 0
    parts.deps.suspend_hotkeys.assert_called_once()
    parts.deps.resume_hotkeys.assert_called_once()


def test_open_settings_when_already_open(qapp: QApplication, tmp_path: Path) -> None:
    """開いていれば前面に出すだけ（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)
    parts.controller.open_settings()
    first_window = parts.controller._settings_window

    # 実行
    parts.controller.open_settings()

    # 検証
    assert parts.controller._settings_window is first_window
    parts.deps.suspend_hotkeys.assert_called_once()
    first_window.try_close()
