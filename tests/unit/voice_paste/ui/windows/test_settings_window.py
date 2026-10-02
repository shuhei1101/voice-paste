"""ui/windows/settings_window.py（SettingsWindow の save、format_hotkey・parse_hotkey・to_field_message）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。UiDeps の関数は Mock に差し替える。
欄は画面設計の項目 ID（field_{キー}・error_summary）の objectName で引く。キーは設定のキーで、エラーの一覧と同じ書式（`outputs[0].enter_delay_sec`）。
エラーの一覧（error_summary）は、行ごとの QLabel（欄へのリンクを含んでよい）で組まれる。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel, QLineEdit, QSlider, QWidget

from tests.unit.voice_paste.ui.helpers import make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.ui.controller import UiDeps
    from voice_paste.ui.windows.settings_window import SettingsWindow

ENTER_DELAY_DESCRIPTION = "貼り付けてから Enter を送るまで待つ秒数"
NEW_VOLUME_PERCENT = 30


@dataclass
class Opened:
    """開いた設定画面と、渡した UiDeps。"""

    window: SettingsWindow
    deps: UiDeps


@pytest.fixture
def opened(qapp: QApplication, tmp_path: Path) -> Iterator[Opened]:
    """既定の設定で設定画面を開き、テストの後に隠す。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    deps = make_ui_deps(tmp_path)
    window = SettingsWindow(deps)
    window.show()
    yield Opened(window=window, deps=deps)
    window.hide()


def _field(window: SettingsWindow, key: str) -> QWidget:
    """設定のキーの欄（objectName が field_{キー}）を返す。"""
    widget = window.findChild(QWidget, f"field_{key}")
    assert widget is not None, f"field_{key} の欄が無い"
    return widget


def _error_summary_text(window: SettingsWindow) -> str:
    """エラーの一覧の行（QLabel）の文字を、リンクの書式を外して改行で並べて返す。"""
    summary = window.findChild(QWidget, "error_summary")
    assert summary is not None
    labels = [summary, *summary.findChildren(QLabel)]
    lines: list[str] = []
    for label in labels:
        if isinstance(label, QLabel):
            document = QTextDocument()
            document.setHtml(label.text())
            lines.append(document.toPlainText())
    return "\n".join(lines)


# === save ===


def test_save(opened: Opened) -> None:
    """通った値を書く（正常系）。"""
    # 準備
    saved_count: list[int] = []
    opened.window.saved.connect(lambda: saved_count.append(1))
    volume = _field(opened.window, "recording.volume_percent")
    assert isinstance(volume, QSlider)
    volume.setValue(NEW_VOLUME_PERCENT)

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].recording.volume_percent == NEW_VOLUME_PERCENT
    assert saved_count == [1]


def test_save_when_invalid(opened: Opened) -> None:
    """通らなければ書かずにエラーを出す（異常系）。"""
    # 準備
    enter_delay = _field(opened.window, "outputs[0].enter_delay_sec")
    assert isinstance(enter_delay, QLineEdit)
    enter_delay.setText("abc")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    assert f"{ENTER_DELAY_DESCRIPTION}: 数値を入れてください（例: 0.5）。" in _error_summary_text(
        opened.window
    )
    assert enter_delay.text() == "abc"


def test_save_when_hotkey_unavailable(opened: Opened) -> None:
    """ホットキーを受け付けられなければエラーを出して閉じない（異常系）。"""
    from voice_paste.shared.errors import HotkeyError

    # 準備
    saved_count: list[int] = []
    opened.window.saved.connect(lambda: saved_count.append(1))
    opened.deps.save_settings.side_effect = HotkeyError("<ctrl>+<nokey> を読めない")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    assert "ホットキーを受け付けられませんでした" in _error_summary_text(opened.window)
    assert saved_count == []
    assert opened.window.isVisible()


# === format_hotkey ===


def test_format_hotkey() -> None:
    """修飾キーと文字を画面の形にする（正常系）。"""
    from voice_paste.ui.windows.settings_window import format_hotkey

    # 実行・検証
    assert format_hotkey("<ctrl>+<alt>+d") == "Ctrl+Alt+D"
    assert format_hotkey("<ctrl>+<shift>+<f5>") == "Ctrl+Shift+F5"


# === parse_hotkey ===


def test_parse_hotkey() -> None:
    """押されたキーを pynput の書式にする（正常系）。"""
    from voice_paste.ui.windows.settings_window import parse_hotkey

    # 準備
    ctrl_alt_d = QKeyCombination(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier, Qt.Key.Key_D
    )
    ctrl_shift_f5 = QKeyCombination(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_F5
    )

    # 実行・検証
    assert parse_hotkey(ctrl_alt_d) == "<ctrl>+<alt>+d"
    assert parse_hotkey(ctrl_shift_f5) == "<ctrl>+<shift>+<f5>"


def test_parse_hotkey_when_modifier_only() -> None:
    """修飾キーだけは入れない（正常系）。"""
    from voice_paste.ui.windows.settings_window import parse_hotkey

    # 準備
    ctrl_only = QKeyCombination(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control)
    escape = QKeyCombination(Qt.Key.Key_Escape)

    # 実行・検証
    assert parse_hotkey(ctrl_only) is None
    assert parse_hotkey(escape) is None


# === to_field_message ===


def test_to_field_message_when_not_number() -> None:
    """数値でない文字（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import Settings
    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {"outputs": [{"id": "paste_and_send", "enter_delay_sec": "abc"}]}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0])

    # 検証
    assert message == "数値を入れてください（例: 0.5）。"


def test_to_field_message_when_out_of_range() -> None:
    """範囲の外（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import Settings
    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate({"api": {"port": 80}})

    # 実行
    message = to_field_message(exc_info.value.errors()[0])

    # 検証
    assert message == "1024〜65535 の値を入れてください。"
