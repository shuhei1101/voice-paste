"""文字起こし中の表示（確定から届けるまで、フォーカスを取らずに出す小さな窓）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from voice_paste.ui.placement import move_to_configured_position
from voice_paste.ui.style import load_tokens, theme_color

if TYPE_CHECKING:
    from voice_paste.ui.controller import UiDeps

TICK_MSEC: int = 100
"""経過と残りの時間を描き直す間隔（ミリ秒）。"""

SPINNER_FRAME_MSEC: int = 16
"""回る印を描き直す間隔（ミリ秒）。"""

SPINNER_SIZE_PX: int = 18
"""回る印の大きさ。"""

SPINNER_ARC_DEGREES: int = 100
"""回る印の弧の長さ（度）。"""

FULL_CIRCLE_DEGREES: int = 360
"""円 1 周の角度。"""

SECONDS_PER_MINUTE: int = 60
"""1 分の秒数。"""

PERCENT: int = 100
"""進みの最大（%）。"""

STATE_TEXT: str = "文字起こし中"
"""状態の表示の文言。"""

HINT_TEXT: str = "貼り付けたい場所にカーソルを合わせてください"
"""貼り付けの案内の文言。"""


def format_elapsed(seconds: float) -> str:
    """経過の時間を、1 分未満は小数 1 桁の秒（3.2 秒）、1 分以上は分と秒（3 分 06 秒）にする。"""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.1f} 秒"
    return format_whole(seconds)


def format_whole(seconds: float) -> str:
    """残り・全体の時間を、1 分未満は整数の秒（2 秒）、1 分以上は分と秒（3 分 06 秒）にする。"""
    whole = round(seconds)
    if whole < SECONDS_PER_MINUTE:
        return f"{whole} 秒"
    minutes, rest = divmod(whole, SECONDS_PER_MINUTE)
    return f"{minutes} 分 {rest:02d} 秒"


class Spinner(QWidget):
    """文字起こし中であることを示す、回る印。"""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(SPINNER_SIZE_PX, SPINNER_SIZE_PX)
        self._angle = 0
        spinner_msec = load_tokens()["motion"]["spinner_ms"]
        self._step = round(FULL_CIRCLE_DEGREES * SPINNER_FRAME_MSEC / spinner_msec)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        """回し始める。"""
        self._timer.start(SPINNER_FRAME_MSEC)

    def stop(self) -> None:
        """回すのを止める。"""
        self._timer.stop()

    def _advance(self) -> None:
        """弧の位置を進めて描き直す。"""
        self._angle = (self._angle + self._step) % FULL_CIRCLE_DEGREES
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 Qt の名前
        """弧を 1 本描く。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme_color("busy"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        margin = 2
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawArc(rect, -self._angle * 16, -SPINNER_ARC_DEGREES * 16)


class TranscribingIndicator(QWidget):
    """確定から届けるまで、経過と残りの時間・進みをフォーカスを取らずに出す。

    残りの時間は、進み（区間の終わり ÷ 録音の長さ）と経過から「経過 ÷ 進み − 経過」で見積もる。
    """

    def __init__(self, deps: UiDeps, *, clock: Callable[[], float] = time.monotonic) -> None:
        """設定の位置を引くための依存と、経過を数える時計（秒を返す関数）を受ける。"""
        super().__init__()
        self._deps = deps
        self._clock = clock
        self._started_at = 0.0
        self._ratio: float | None = None
        self._duration_sec = 0.0
        self.setObjectName("transcribing_indicator")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_time)

    def _build(self) -> None:
        """状態・進みのバー・経過と残りの時間・貼り付けの案内を並べる。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setProperty("role", "surface")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QHBoxLayout()
        self._spinner = Spinner()
        header.addWidget(self._spinner)
        state_label = QLabel(STATE_TEXT)
        state_label.setObjectName("state_label")
        state_label.setProperty("role", "busy")
        header.addWidget(state_label)
        header.addStretch(1)
        layout.addLayout(header)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("progress_bar")
        self._progress_bar.setRange(0, PERCENT)
        self._progress_bar.setTextVisible(False)
        # 最初の区間の終わりが届くまでは、回る印だけを出す
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        self._time_label = QLabel()
        self._time_label.setObjectName("time_label")
        self._time_label.setProperty("role", "mono")
        layout.addWidget(self._time_label)

        hint = QLabel(HINT_TEXT)
        hint.setObjectName("paste_hint")
        hint.setProperty("role", "muted")
        layout.addWidget(hint)

    def open(self) -> None:
        """経過を 0 にして進みを隠し、録音の画面と同じ位置に出す。"""
        settings = self._deps.get_settings()
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        if settings.ui.topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self._started_at = self._clock()
        self._ratio = None
        self._progress_bar.setValue(0)
        self._progress_bar.hide()
        self._refresh_time()

        move_to_configured_position(self, settings.ui)
        self.show()
        self._spinner.start()
        self._timer.start(TICK_MSEC)

    def set_progress(self, position_sec: float, duration_sec: float) -> None:
        """進みのバーと残りの時間を書き換える。"""
        if duration_sec <= 0:
            return
        self._ratio = min(position_sec / duration_sec, 1.0)
        self._duration_sec = duration_sec
        self._progress_bar.setValue(round(self._ratio * PERCENT))
        self._progress_bar.show()
        self._refresh_time()

    def close_window(self) -> None:
        """タイマーと回る印を止めて窓を隠す。"""
        self._timer.stop()
        self._spinner.stop()
        self.hide()

    def _refresh_time(self) -> None:
        """経過と、見積もった残りの時間・全体の時間の文字を書き換える。"""
        elapsed = self._clock() - self._started_at
        # 最初の区間の終わりが届くまでは、残りを計っている
        if self._ratio is None or self._ratio <= 0:
            self._time_label.setText(f"経過 {format_elapsed(elapsed)} 残りを計っています")
            return
        remaining = max(elapsed / self._ratio - elapsed, 0.0)
        self._time_label.setText(
            f"経過 {format_elapsed(elapsed)} 残り {format_whole(remaining)}"
            f" / {format_whole(self._duration_sec)}"
        )
