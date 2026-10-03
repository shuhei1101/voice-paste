"""録音の画面（ホットキー・トレイから始めた録音の間だけ出る小さな窓）。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.settings import Preset, Settings
from voice_paste.ui.placement import move_to_configured_position
from voice_paste.ui.style import theme_color
from voice_paste.ui.windows.settings_window import OUTPUT_NAMES, PRESET_KIND_NAMES, format_hotkey

if TYPE_CHECKING:
    from voice_paste.ui.controller import UiDeps

WAVE_INTERVAL_MS: int = 50
"""録音の画面が経過時間と波形を描き直す間隔。PoC で 100 ms ごとのタイマーの発火の間隔の最大が 123 ms だったため、波形が滑らかに流れる 50 ms にしてもメインスレッドを塞がない。"""

WAVE_BAR_COUNT: int = 24
"""録音の画面の波形に並べる棒の本数。"""

WAVE_HEIGHT_PX: int = 48
"""波形の高さ。"""

WAVE_BAR_MIN_PX: float = 2.0
"""無音のときも出す、棒の最小の高さ。"""

WAVE_BAR_GAP_PX: float = 3.0
"""棒の間の幅。"""

PRESET_NAME_MAX_PX: int = 120
"""カスタムプリセットのボタンで、タイトルを `…` に省略する幅。"""

PRESET_COLUMNS: int = 3
"""カスタムプリセットのボタンを横に並べる数（これを超えたら次の行へ折り返す）。"""

SECONDS_PER_HOUR: int = 3600
SECONDS_PER_MINUTE: int = 60
"""経過時間の表示の区切り。"""

MSEC_PER_SECOND: int = 1000
"""1 秒のミリ秒。"""


def format_clock(elapsed_ms: int) -> str:
    """経過時間を、1 時間未満は `mm:ss`、1 時間以上は `h:mm:ss` にする。"""
    seconds = elapsed_ms // MSEC_PER_SECOND
    hours, rest = divmod(seconds, SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class Waveform(QWidget):
    """録音中の音量を棒の並びで流す。一時停止中は棒を止め、最後の形のまま出す。"""

    def __init__(self, levels: deque[float]) -> None:
        super().__init__()
        self.setObjectName("waveform")
        self.setFixedHeight(WAVE_HEIGHT_PX)
        self._levels = levels
        self.paused = False

    def paintEvent(self, event: object) -> None:  # noqa: N802 Qt の名前
        """直近の音量を、左から右へ棒で描く。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme_color("paused" if self.paused else "recording"))
        count = len(self._levels)
        width = self.width() / max(count, 1)
        for index, level in enumerate(self._levels):
            height = max(level * self.height(), WAVE_BAR_MIN_PX)
            rect = QRectF(
                index * width,
                (self.height() - height) / 2,
                max(width - WAVE_BAR_GAP_PX, 1.0),
                height,
            )
            painter.drawRoundedRect(rect, 1.5, 1.5)


class RecordingWindow(QWidget):
    """状態・経過時間・波形と、一時停止・取り消し・確定のボタンを並べる小さな窓。

    窓は Tool・枠なしで、出したときにフォーカスを取らない（`ui.topmost` がオンなら最前面）。
    経過時間は窓が持つストップウォッチで数え、経過時間と波形は WAVE_INTERVAL_MS ごとのタイマーで描き直す。
    """

    def __init__(self, deps: UiDeps) -> None:
        """確定・一時停止・取り消し・音量・設定を受ける関数の束を受ける。"""
        super().__init__()
        self._deps = deps
        self._levels: deque[float] = deque([0.0] * WAVE_BAR_COUNT, maxlen=WAVE_BAR_COUNT)
        self._stopwatch = QElapsedTimer()
        self._accumulated_ms = 0
        self._running = False
        self.setObjectName("recording_window")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # --- 組み立て ---

    def _build(self) -> None:
        """状態・経過時間・波形・操作の行・確定のボタンの置き場を並べる（ボタンは open が組み直す）。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setProperty("role", "surface")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self._state_label = QLabel()
        self._state_label.setObjectName("state_label")
        header.addWidget(self._state_label)
        header.addStretch(1)
        self._elapsed_label = QLabel(format_clock(0))
        self._elapsed_label.setObjectName("elapsed_label")
        self._elapsed_label.setProperty("role", "time")
        self._elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._elapsed_label)
        layout.addLayout(header)

        self._waveform = Waveform(self._levels)
        layout.addWidget(self._waveform)

        # 操作の行: 一時停止（再開と同じ場所）・取り消し
        self._operations = QHBoxLayout()
        layout.addLayout(self._operations)

        self._outputs_heading = self._heading("outputs_heading", "確定して届ける")
        layout.addWidget(self._outputs_heading)
        self._outputs_layout = QHBoxLayout()
        layout.addLayout(self._outputs_layout)
        self._presets_heading = self._heading("presets_heading", "カスタムプリセット")
        layout.addWidget(self._presets_heading)
        self._presets_layout = QGridLayout()
        layout.addLayout(self._presets_layout)

    @staticmethod
    def _heading(name: str, text: str) -> QLabel:
        """出力先の並びの見出しを作る。"""
        label = QLabel(text)
        label.setObjectName(name)
        label.setProperty("role", "muted")
        return label

    @staticmethod
    def _hotkey_button(name: str, text: str, hotkey: str, *, tooltip: str | None = None) -> QPushButton:
        """名前の右にホットキーを出すボタンを作る（ホットキーは省略しない）。"""
        button = QPushButton()
        button.setObjectName(name)
        layout = QHBoxLayout(button)
        layout.setContentsMargins(0, 0, 0, 0)
        text_label = QLabel(text)
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(text_label)
        # ホットキーが空のときは、名前だけを出す
        if hotkey:
            key_label = QLabel(format_hotkey(hotkey))
            key_label.setProperty("role", "mono")
            key_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addStretch(1)
            layout.addWidget(key_label)
        if tooltip:
            button.setToolTip(tooltip)
        return button

    @staticmethod
    def _clear(layout: QLayout) -> None:
        """レイアウトの中の部品を全て外して捨てる。"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_buttons(self, settings: Settings) -> None:
        """設定でオンの出力先と有効なカスタムプリセットのボタンを、設定の並びで組み直す。"""
        for layout in (self._operations, self._outputs_layout, self._presets_layout):
            self._clear(layout)

        self._pause_button = self._hotkey_button("pause_button", "一時停止", settings.hotkeys.pause)
        self._pause_button.clicked.connect(self._deps.pause)
        self._resume_button = self._hotkey_button("resume_button", "再開", settings.hotkeys.pause)
        self._resume_button.clicked.connect(self._deps.resume)
        self._resume_button.hide()
        cancel_button = self._hotkey_button("cancel_button", "取り消す", settings.hotkeys.cancel)
        cancel_button.clicked.connect(self._cancel)
        for button in (self._pause_button, self._resume_button, cancel_button):
            self._operations.addWidget(button)

        # 出力先の確定のボタン（オンのうち一番上のものを主の操作にする）
        shown_outputs = 0
        for output in settings.outputs:
            if not output.enabled:
                continue
            button = self._hotkey_button(
                f"output_button_{output.id}", OUTPUT_NAMES[output.id], output.hotkey
            )
            button.setProperty("primary", shown_outputs == 0)
            button.clicked.connect(
                lambda _checked=False, output_id=output.id: self._complete(output_id, None)
            )
            self._outputs_layout.addWidget(button)
            shown_outputs += 1
        self._outputs_heading.setVisible(shown_outputs > 0)

        # カスタムプリセットのボタン（有効なものを、種類の並び（PRESET_KIND_NAMES）の順に、種類の中は設定の並びで。
        # 3 件ずつ横に並べ、種類の境目でも行を変えない。タイトルは幅で省略し、かざすと全体を出す）
        shown_presets = 0
        for kind in PRESET_KIND_NAMES:
            for preset in settings.presets:
                if preset.kind != kind or not preset.enabled:
                    continue
                elided = QFontMetrics(self.font()).elidedText(
                    preset.title, Qt.TextElideMode.ElideRight, PRESET_NAME_MAX_PX
                )
                button = self._hotkey_button(
                    f"preset_button_{shown_presets}", elided, preset.hotkey, tooltip=preset.title
                )
                button.clicked.connect(
                    lambda _checked=False, chosen=preset: self._complete(None, chosen)
                )
                row, column = divmod(shown_presets, PRESET_COLUMNS)
                self._presets_layout.addWidget(button, row, column)
                shown_presets += 1
        self._presets_heading.setVisible(shown_presets > 0)

    # --- 操作 ---

    def _complete(self, output_id: str | None, preset: Preset | None) -> None:
        """押したボタンの出力先かプリセットで録音を確定し、窓を閉じる。"""
        self._deps.complete(output_id, preset)
        self.close_window()

    def _cancel(self) -> None:
        """録音を捨てて窓を閉じる。"""
        self._deps.cancel()
        self.close_window()

    # --- 開く・替える・閉じる ---

    def open(self) -> None:
        """新しい録音として経過時間と波形を空にし、設定でオンの出力先と有効なカスタムプリセットのボタンを組み直して、設定の位置に出す。"""
        settings = self._deps.get_settings()
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if settings.ui.topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self._rebuild_buttons(settings)

        self._levels.extend([0.0] * WAVE_BAR_COUNT)
        self._waveform.paused = False
        self._accumulated_ms = 0
        self._stopwatch.start()
        self._running = True
        self._show_state(paused=False)
        self._elapsed_label.setText(format_clock(0))

        move_to_configured_position(self, settings.ui)
        self.show()
        self._timer.start(WAVE_INTERVAL_MS)

    def set_paused(self, paused: bool) -> None:
        """状態の表示と一時停止・再開のボタンを替え、経過時間と波形を止める・動かす。"""
        # 止める: ここまでの経過を貯めて数えるのをやめる／動かす: 数え直す
        if paused and self._running:
            self._accumulated_ms += self._stopwatch.elapsed()
            self._running = False
        elif not paused and not self._running:
            self._stopwatch.restart()
            self._running = True
        self._waveform.paused = paused
        self._show_state(paused=paused)

    def close_window(self) -> None:
        """タイマーを止めて窓を隠す。"""
        self._timer.stop()
        self._running = False
        self.hide()

    def _show_state(self, *, paused: bool) -> None:
        """状態の表示（印と文字）と、一時停止・再開のどちらのボタンを出すかを替える。"""
        self._state_label.setText("● 一時停止中" if paused else "● 録音中")
        self._state_label.setProperty("role", "paused" if paused else "recording")
        self._state_label.style().unpolish(self._state_label)
        self._state_label.style().polish(self._state_label)
        self._pause_button.setVisible(not paused)
        self._resume_button.setVisible(paused)

    def _tick(self) -> None:
        """経過時間と波形を描き直す（一時停止の間は止める）。"""
        if not self._running:
            return
        elapsed_ms = self._accumulated_ms + self._stopwatch.elapsed()
        self._elapsed_label.setText(format_clock(elapsed_ms))
        gain = self._deps.get_settings().ui.wave_gain
        self._levels.append(min(self._deps.level() * gain, 1.0))
        self._waveform.update()
