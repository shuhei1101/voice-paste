"""ui/windows/transcribing_indicator.py（TranscribingIndicator の open・set_progress・set_output）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。経過は進められる時計に差し替える。
欄は画面設計の項目 ID（progress_bar・time_label・paste_hint・preset_label・switch_button_{output_id}）の objectName で引く。
切り替えのボタンの選んだ状態は QPushButton.isChecked() で確かめる。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton

from tests.unit.voice_paste.ui.helpers import OUTPUT_TITLES, FakeClock, make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def test_open_when_window_role(qapp: QApplication, tmp_path: Path) -> None:
    """窓の外側の枠の role が window（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))

    # 実行
    indicator.open()

    # 検証
    outer_frames = indicator.findChildren(QFrame, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert [frame.property("role") for frame in outer_frames] == ["window"]


def test_open_when_preset(qapp: QApplication, tmp_path: Path) -> None:
    """カスタムプリセットで確定したときは名前だけを出す（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))

    # 実行
    indicator.open(preset_title="ChatGPT")

    # 検証
    preset_label = indicator.findChild(QLabel, "preset_label")
    switch_buttons = indicator.findChildren(QPushButton, QRegularExpression("^switch_button_"))
    paste_hints = indicator.findChildren(QLabel, "paste_hint")
    assert preset_label.text() == "ChatGPT"
    assert [button for button in switch_buttons if button.isVisible()] == []
    assert [hint for hint in paste_hints if hint.isVisible()] == []


def test_set_progress(qapp: QApplication, tmp_path: Path) -> None:
    """進みと残りを出す（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 時計は表示を出したとき 0 秒、進みを受けたとき 3.0 秒
    clock = FakeClock(0.0)
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=clock)
    indicator.open()
    clock.now = 3.0

    # 実行
    indicator.set_progress(3.1, 5.0)

    # 検証
    progress_bar = indicator.findChild(QProgressBar, "progress_bar")
    time_label = indicator.findChild(QLabel, "time_label")
    assert progress_bar.value() == 62
    assert time_label.text() == "経過 3.0 秒 残り 2 秒 / 5 秒"


def test_set_output(qapp: QApplication, tmp_path: Path) -> None:
    """印と案内を切り替えた先に替える（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 貼り付けて送信・貼り付けのみ・コピーのみがオンの設定で、貼り付けて送信で確定した表示を出す
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))
    indicator.open(output_id="paste_and_send")

    # 実行
    indicator.set_output("copy_only")

    # 検証
    checked = {
        output_id: indicator.findChild(QPushButton, f"switch_button_{output_id}").isChecked()
        for output_id in OUTPUT_TITLES
    }
    paste_hint = indicator.findChild(QLabel, "paste_hint")
    assert checked == {"paste_and_send": False, "paste_only": False, "copy_only": True}
    assert paste_hint.text() == "起こした文字をクリップボードにコピーします"
