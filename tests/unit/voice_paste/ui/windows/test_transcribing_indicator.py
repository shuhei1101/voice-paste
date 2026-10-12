"""ui/windows/transcribing_indicator.py（TranscribingIndicator の open・set_progress）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。経過は進められる時計に差し替える。
欄は画面設計の項目 ID（progress_bar・time_label）の objectName で引く。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar

from tests.unit.voice_paste.ui.helpers import FakeClock, make_ui_deps

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
