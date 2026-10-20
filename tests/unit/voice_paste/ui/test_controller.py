"""ui/controller.py（UiController の on_notified・on_copied・recopy・request_exit・open_settings・hide_recording・show_recording・eventFilter）の単体テスト。

UiDeps の関数・トレイ・録音の画面・文字起こし中の表示は Mock に差し替える（設定画面だけは本物を開く）。
画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, QTimer
from PySide6.QtWidgets import QSlider, QWidget

from tests.unit.voice_paste.ui.helpers import FakeClock, make_session, make_ui_deps
from voice_paste.shared.errors import DeliveryError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings
    from voice_paste.ui.controller import UiController, UiDeps

NEW_VOLUME_PERCENT = 30
QUIT_TIMEOUT_MS = 2000
"""終了で抜けられないときにイベントループを止めるまでの時間。"""
QUIT_TIMEOUT_EXIT_CODE = -1
"""QUIT_TIMEOUT_MS で止めたときのイベントループの終了コード。"""
REOPEN_COUNT = 5
"""設定画面の開き閉めを繰り返す回数。"""


@dataclass
class Parts:
    """UiController と、注入した偽物。"""

    controller: UiController
    deps: UiDeps
    tray: MagicMock
    recording_window: MagicMock
    indicator: MagicMock


def _make_controller(
    tmp_path: Path, *, settings: Settings | None = None, **deps_overrides: Any
) -> Parts:
    """UiDeps の関数・トレイ・録音の画面・文字起こし中の表示を Mock にした UiController を作る。deps_overrides は UiDeps の項目ごとの差し替え。"""
    from voice_paste.ui.controller import UiController

    deps = make_ui_deps(tmp_path, settings=settings, **deps_overrides)
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


def _open_recording_window(parts: Parts) -> None:
    """ホットキーの録音を知らせて、録音の画面を出した状態にする。"""
    parts.deps.current_session.return_value = make_session("hotkey", "recording")
    parts.controller.on_notified("state_changed", None)


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


def test_on_notified_when_recording_hidden(qapp: QApplication, tmp_path: Path) -> None:
    """隠した録音の画面は、一時停止しても出さずに状態だけ替える（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備: 画面を出して隠した後、隠した状態の呼び出しだけを数える
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)
    parts.controller.hide_recording()
    parts.recording_window.reset_mock()
    parts.tray.reset_mock()
    parts.deps.current_session.return_value = make_session("hotkey", "paused")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.recording_window.set_paused.assert_called_with(True)
    parts.recording_window.open.assert_not_called()
    parts.recording_window.restore.assert_not_called()
    parts.tray.set_recording_window.assert_called_with(RecordingWindowState.HIDDEN)


def test_on_notified_when_transcribing_after_hidden(qapp: QApplication, tmp_path: Path) -> None:
    """動かして隠したまま確定した回も、文字起こし中の表示を動かした位置に出す（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備: 画面を出して隠し、動かした位置を (300, 200) にする
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)
    parts.controller.hide_recording()
    parts.recording_window.moved_position.return_value = QPoint(300, 200)
    parts.deps.current_session.return_value = make_session("hotkey", "transcribing")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.indicator.open.assert_called_once()
    assert parts.indicator.open.call_args.kwargs["at"] == QPoint(300, 200)
    parts.tray.set_recording_window.assert_called_with(RecordingWindowState.NOT_RECORDING)


def test_on_notified_when_show_recording_window(qapp: QApplication, tmp_path: Path) -> None:
    """ホットキーからの指示で隠した録音の画面を戻す（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備: 画面を出して隠した後、隠した状態の呼び出しだけを数える
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)
    parts.controller.hide_recording()
    parts.recording_window.reset_mock()
    parts.tray.reset_mock()

    # 実行
    parts.controller.on_notified("show_recording_window", None)

    # 検証
    parts.recording_window.restore.assert_called_once()
    parts.tray.set_recording_window.assert_called_with(RecordingWindowState.SHOWN)


def test_on_notified_when_transcribing_without_move(qapp: QApplication, tmp_path: Path) -> None:
    """動かしていない回は、文字起こし中の表示を設定の位置に出す（正常系）。"""
    # 準備: 画面を出し、動かしていない（動かした位置が None）まま確定する
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)
    parts.recording_window.moved_position.return_value = None
    parts.deps.current_session.return_value = make_session("hotkey", "transcribing")

    # 実行
    parts.controller.on_notified("state_changed", None)

    # 検証
    parts.indicator.open.assert_called_once()
    assert parts.indicator.open.call_args.kwargs["at"] is None


def test_on_notified_when_output_changed(qapp: QApplication, tmp_path: Path) -> None:
    """出力先の差し替えを文字起こし中の表示へ渡す（正常系）。"""
    # 準備: 貼り付けて送信で確定した文字起こし中の表示を出した状態にする
    parts = _make_controller(tmp_path)
    parts.deps.current_session.return_value = make_session(
        "hotkey", "transcribing", output_id="paste_and_send"
    )
    parts.controller.on_notified("state_changed", None)

    # 実行
    parts.controller.on_notified("output_changed", "copy_only")

    # 検証
    parts.indicator.set_output.assert_called_once_with("copy_only")
    parts.indicator.open.assert_called_once()


def test_on_notified_when_transcribing_with_output(qapp: QApplication, tmp_path: Path) -> None:
    """文字起こし中の表示へ確定した出力先・プリセットを渡して開く（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備: 固定の出力先で確定した回と、カスタムプリセットで確定した回を、別のコントローラで受ける
    preset = BrowserPreset(title="ChatGPT", url="https://chatgpt.com")
    with_output = _make_controller(tmp_path)
    with_output.deps.current_session.return_value = make_session(
        "hotkey", "transcribing", output_id="paste_and_send"
    )
    with_preset = _make_controller(tmp_path)
    with_preset.deps.current_session.return_value = make_session(
        "hotkey", "transcribing", output_preset=preset
    )

    # 実行
    with_output.controller.on_notified("state_changed", None)
    with_preset.controller.on_notified("state_changed", None)

    # 検証
    with_output.indicator.open.assert_called_once_with(
        at=None, output_id="paste_and_send", preset_title=None
    )
    with_preset.indicator.open.assert_called_once_with(
        at=None, output_id=None, preset_title="ChatGPT"
    )


def test_on_notified_when_output_selected(qapp: QApplication, tmp_path: Path) -> None:
    """文字起こし中の表示で選んだ出力先を差し替えへ渡す（正常系）。"""
    from voice_paste.ui.controller import UiController
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備
    deps = make_ui_deps(tmp_path)
    indicator = TranscribingIndicator(deps, clock=FakeClock(0.0))
    _controller = UiController(
        deps, tray=MagicMock(), recording_window=MagicMock(), indicator=indicator
    )

    # 実行
    indicator.output_selected.emit("paste_only")

    # 検証
    deps.switch_output.assert_called_once_with("paste_only")


# === on_copied ===


def test_on_copied(qapp: QApplication, tmp_path: Path) -> None:
    """コピーの完了をトレイの通知で知らせる（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)

    # 実行
    parts.controller.on_copied("テスト")

    # 検証
    parts.tray.show_copy_completed.assert_called_once_with("テスト")


# === recopy ===


def test_recopy(qapp: QApplication, tmp_path: Path) -> None:
    """起こした文字をコピーし直す（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)

    # 実行
    parts.controller.recopy("テスト")

    # 検証
    parts.deps.copy.assert_called_once_with("テスト")
    parts.tray.show_failure.assert_not_called()


def test_recopy_when_copy_failed(
    qapp: QApplication, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """コピーし直せなければ届けられなかったことを知らせる（異常系）。"""
    # 準備
    caplog.set_level(logging.ERROR)
    copy = MagicMock(side_effect=DeliveryError("クリップボードへ書けませんでした"))
    parts = _make_controller(tmp_path, copy=copy)

    # 実行
    parts.controller.recopy("テスト")

    # 検証
    parts.tray.show_failure.assert_called_once_with(
        "delivery_failed", "クリップボードへ書けませんでした"
    )
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1


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


def _flush_deferred_deletes(qapp: QApplication) -> None:
    """deleteLater の破棄を流して、Python 側の参照も回収する。"""
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def _reopen_settings(parts: Parts, qapp: QApplication, times: int) -> int:
    """設定画面を開いて取り消しで閉じるのを times 回繰り返し、毎回破棄を流す。開いた窓が互いに別物だった数を返す。"""
    opened: list[QWidget] = []
    distinct_count = 0
    for _ in range(times):
        parts.controller.open_settings()
        window = parts.controller._settings_window
        assert window is not None
        # 前に開いた窓と同じ物ではない（毎回新しく開いた）
        if all(window is not previous for previous in opened):
            distinct_count += 1
        opened.append(window)
        window.try_close()
        _flush_deferred_deletes(qapp)
    return distinct_count


def test_open_settings_when_reopened(qapp: QApplication, tmp_path: Path) -> None:
    """開き閉めを繰り返しても窓が積もらない（正常系）。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    # 準備: 前のテストの破棄待ちを流した時点のトップレベルの窓の数を控える
    parts = _make_controller(tmp_path)
    _flush_deferred_deletes(qapp)
    top_level_count_before = len(qapp.topLevelWidgets())

    # 実行
    distinct_count = _reopen_settings(parts, qapp, REOPEN_COUNT)
    _flush_deferred_deletes(qapp)

    # 検証
    remaining_windows = [w for w in qapp.topLevelWidgets() if isinstance(w, SettingsWindow)]
    assert distinct_count == REOPEN_COUNT
    assert remaining_windows == []
    assert len(qapp.topLevelWidgets()) == top_level_count_before


# === on_settings_saved ===


def test_on_settings_saved(qapp: QApplication, tmp_path: Path) -> None:
    """保存したら明暗を当て直す（正常系）。"""
    from voice_paste.main import SETTINGS_MODEL

    # 準備: ui.theme=dark の設定が効いている
    settings = SETTINGS_MODEL.model_validate({"ui": {"theme": "dark"}})
    apply_theme = MagicMock(return_value=None)
    parts = _make_controller(tmp_path, settings=settings, apply_theme=apply_theme)

    # 実行
    parts.controller.on_settings_saved()

    # 検証
    apply_theme.assert_called_once_with()
    parts.tray.set_start_hotkey.assert_called_once_with(settings.hotkeys.start)


# === hide_recording ===


def test_hide_recording(qapp: QApplication, tmp_path: Path) -> None:
    """録音の画面を隠してトレイの項目を押せるようにする（正常系）。"""
    from voice_paste.ui.tray import RecordingWindowState

    # 準備
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)

    # 実行
    parts.controller.hide_recording()

    # 検証
    parts.recording_window.hide_window.assert_called_once()
    parts.tray.set_recording_window.assert_called_with(RecordingWindowState.HIDDEN)


# === show_recording ===


def test_show_recording_when_not_hidden(qapp: QApplication, tmp_path: Path) -> None:
    """隠していなければ何もしない（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)
    _open_recording_window(parts)

    # 実行
    parts.controller.show_recording()

    # 検証
    parts.recording_window.restore.assert_not_called()


# === eventFilter ===


def test_event_filter_when_quit_with_settings_open(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """設定画面を開いて欄を変えたまま終了しても、確かめずに閉じてイベントループを抜ける（正常系）。"""
    # 準備: 設定画面を開いて欄を変え、捨てる確認が出たら「捨てない」と答える
    confirm_discard = MagicMock(return_value=False)
    monkeypatch.setattr("voice_paste.ui.windows.settings_window.confirm_discard", confirm_discard)
    parts = _make_controller(tmp_path)
    parts.controller.open_settings()
    settings_window = parts.controller._settings_window
    assert settings_window is not None
    volume = settings_window.findChild(QWidget, "field_recording.volume_percent")
    assert isinstance(volume, QSlider)
    volume.setValue(NEW_VOLUME_PERCENT)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: qapp.exit(QUIT_TIMEOUT_EXIT_CODE))

    # 実行: イベントループの中で終了を頼む（抜けられなければ時間切れで止める）
    QTimer.singleShot(0, qapp.quit)
    timeout.start(QUIT_TIMEOUT_MS)
    exit_code = qapp.exec()
    timeout.stop()
    settings_window.hide()

    # 検証
    confirm_discard.assert_not_called()
    assert parts.controller._settings_window is None
    assert exit_code == 0
    parts.deps.save_settings.assert_not_called()


def test_event_filter_when_quit_without_settings(qapp: QApplication, tmp_path: Path) -> None:
    """設定画面を開いていなければ何もしない（正常系）。"""
    # 準備
    parts = _make_controller(tmp_path)

    # 実行
    result = parts.controller.eventFilter(qapp, QEvent(QEvent.Type.Quit))

    # 検証
    assert result is False
    parts.deps.resume_hotkeys.assert_not_called()
