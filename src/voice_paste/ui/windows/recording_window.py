"""録音の画面（ホットキー・トレイから始めた録音の間だけ出る小さな窓）。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QLineF,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QEnterEvent, QFontMetrics, QMouseEvent, QPaintEvent, QPainter, QPen
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
from voice_paste.ui.windows.settings_window import PRESET_KIND_NAMES, format_hotkey

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

HEAD_BUTTON_SIZE_PX: int = 28
"""見出しの行の「隠す」「×」のボタンの一辺。"""

HEAD_BUTTON_GLYPH_HALF_PX: float = 4.5
"""「隠す」の横線・「×」の斜めの線の、中心から端までの長さ。"""

HEAD_BUTTON_PEN_PX: float = 1.5
"""「隠す」「×」の線の太さ。"""

HEAD_DIVIDER_HEIGHT_PX: int = 16
"""「隠す」と「×」の間の区切りの線の高さ。"""

HEAD_TOOLS_GAP_PX: int = 6
"""「隠す」「×」と区切りの線の間の幅（押し違えないよう空ける）。"""

GRIP_SIZE: tuple[int, int] = (12, 16)
"""つかむ印の幅と高さ。"""

GRIP_DOT_RADIUS_PX: float = 1.4
"""つかむ印の点の半径。"""

GRIP_COLUMNS: tuple[float, ...] = (3.0, 9.0)
GRIP_ROWS: tuple[float, ...] = (3.0, 8.0, 13.0)
"""つかむ印の点を置く列と段の座標（2 列 3 段）。"""


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


class HeadRow(QWidget):
    """見出しの行。どこをつかんでも（子のボタンの上を除く）押したまま動かすと窓を動かす。"""

    drag_started = Signal()
    """窓の移動を OS に任せる直前（動かす前の位置を控える合図）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("head_row")
        self.setProperty("role", "head_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("ドラッグで動かす")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 Qt の名前
        """左ボタンで押したら、OS に窓の移動を任せる（動かしている間も録音と経過時間は止めない）。"""
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            self.drag_started.emit()
            handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 Qt の名前
        """かざしたら、つかむ印を濃くするために子を描き直す。"""
        super().enterEvent(event)
        for child in self.findChildren(GripIcon):
            child.update()

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 Qt の名前
        """外れたら、つかむ印を戻すために子を描き直す。"""
        super().leaveEvent(event)
        for child in self.findChildren(GripIcon):
            child.update()


class GripIcon(QWidget):
    """窓をつかめることを示す、点を 2 列 3 段に並べた印。見出しの行にかざしている間は濃くする。"""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(*GRIP_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: object) -> None:  # noqa: N802 Qt の名前
        """点を 6 つ描く。"""
        row = self.parentWidget()
        hovered = row is not None and row.underMouse()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme_color("text" if hovered else "text_muted"))
        for y in GRIP_ROWS:
            for x in GRIP_COLUMNS:
                painter.drawEllipse(QPointF(x, y), GRIP_DOT_RADIUS_PX, GRIP_DOT_RADIUS_PX)


class HeadButton(QPushButton):
    """見出しの行の、枠を持たないアイコンのボタン（「隠す」の横線・「×」）。かざすと面を出す。"""

    def __init__(self, name: str, *, close: bool) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setProperty("role", "head_close" if close else "head_button")
        self.setFixedSize(HEAD_BUTTON_SIZE_PX, HEAD_BUTTON_SIZE_PX)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._close = close

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 Qt の名前
        """面と枠を描いた後、線を描く（かざしている間は濃く、「×」は警告の色にする）。"""
        super().paintEvent(event)
        if self.underMouse():
            color = theme_color("danger" if self._close else "text")
        else:
            color = theme_color("text_muted")
        pen = QPen(color, HEAD_BUTTON_PEN_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        cx, cy, half = self.width() / 2, self.height() / 2, HEAD_BUTTON_GLYPH_HALF_PX
        # 「×」は斜めの 2 本、「隠す」は横の 1 本（最小化の形）
        if self._close:
            painter.drawLine(QLineF(cx - half, cy - half, cx + half, cy + half))
            painter.drawLine(QLineF(cx + half, cy - half, cx - half, cy + half))
        else:
            painter.drawLine(QLineF(cx - half, cy, cx + half, cy))


class RecordingWindow(QWidget):
    """状態・経過時間・波形と、一時停止・取り消し・確定のボタンを並べる小さな窓。

    窓は Tool・枠なしで、出したときにフォーカスを取らない（`ui.topmost` がオンなら最前面）。
    経過時間は窓が持つストップウォッチで数え、経過時間と波形は WAVE_INTERVAL_MS ごとのタイマーで描き直す。
    見出しの行（状態・経過時間・隠す・×）は、隠す・× の外を押したまま動かすと窓を動かす。
    """

    hide_requested = Signal()
    """「隠す」のボタンが押された（隠すのは UiController）。"""

    def __init__(self, deps: UiDeps) -> None:
        """確定・一時停止・取り消し・音量・設定を受ける関数の束を受ける。"""
        super().__init__()
        self._deps = deps
        self._levels: deque[float] = deque([0.0] * WAVE_BAR_COUNT, maxlen=WAVE_BAR_COUNT)
        self._stopwatch = QElapsedTimer()
        self._accumulated_ms = 0
        self._running = False
        self._drag_origin: QPoint | None = None
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

        # 見出しの行: つかむ印・状態・経過時間・隠す・×（行のどこをつかんでも窓を動かせる）
        head_row = HeadRow()
        head_row.drag_started.connect(self._remember_drag_origin)
        header = QHBoxLayout(head_row)
        header.setContentsMargins(4, 4, 4, 4)
        header.setSpacing(HEAD_TOOLS_GAP_PX)
        header.addWidget(GripIcon())
        self._state_label = QLabel()
        self._state_label.setObjectName("state_label")
        self._state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self._state_label)
        header.addStretch(1)
        self._elapsed_label = QLabel(format_clock(0))
        self._elapsed_label.setObjectName("elapsed_label")
        self._elapsed_label.setProperty("role", "time")
        self._elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._elapsed_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self._elapsed_label)
        self._hide_button = HeadButton("hide_button", close=False)
        self._hide_button.setAccessibleName("録音の画面を隠す")
        self._hide_button.clicked.connect(self.hide_requested)
        header.addWidget(self._hide_button)
        divider = QFrame()
        divider.setObjectName("head_divider")
        divider.setProperty("role", "head_divider")
        divider.setFixedSize(1, HEAD_DIVIDER_HEIGHT_PX)
        header.addWidget(divider)
        self._close_button = HeadButton("close_button", close=True)
        self._close_button.setAccessibleName("取り消す")
        self._close_button.clicked.connect(self._cancel)
        header.addWidget(self._close_button)
        layout.addWidget(head_row)

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
                f"output_button_{output.id}", self._deps.output_titles[output.id], output.hotkey
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

    def _update_head_tooltips(self, settings: Settings) -> None:
        """「隠す」には戻し方を、「×」には取り消しのホットキーを、かざしたときの説明に添える。"""
        start = settings.hotkeys.start
        # 録音開始と同じホットキーの出力先がある設定では、ホットキーは確定に使われるため、トレイのアイコンだけで戻す
        confirms_with_start = any(
            output.enabled and output.hotkey.lower() == start.lower() for output in settings.outputs
        )
        restore_by = (
            "トレイのアイコンで戻す"
            if confirms_with_start or not start
            else f"トレイのアイコンか {format_hotkey(start)} で戻す"
        )
        self._hide_button.setToolTip(f"録音の画面を隠す（{restore_by}）")
        cancel = settings.hotkeys.cancel
        self._close_button.setToolTip(
            f"取り消す（{format_hotkey(cancel)}）" if cancel else "取り消す"
        )

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
        self._update_head_tooltips(settings)

        self._levels.extend([0.0] * WAVE_BAR_COUNT)
        self._waveform.paused = False
        self._accumulated_ms = 0
        self._stopwatch.start()
        self._running = True
        self._show_state(paused=False)
        self._elapsed_label.setText(format_clock(0))

        move_to_configured_position(self, settings.ui)
        self._drag_origin = None
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

    def hide_window(self) -> None:
        """その回の録音を続けたまま窓を隠す。ストップウォッチは止めず、描き直しのタイマーだけを止める。窓の位置は残す。"""
        self._timer.stop()
        self.hide()

    def restore(self) -> None:
        """隠した窓を、経過時間・波形・ボタンを組み直さずに、隠す前の位置へフォーカスを取らずに出し、描き直しのタイマーを動かす。"""
        # 隠している間に進んだ（一時停止していれば止まった）経過時間を先に描き直してから出す
        self._refresh_clock()
        self.show()
        self._timer.start(WAVE_INTERVAL_MS)

    def moved_position(self) -> QPoint | None:
        """その回に窓を動かしていれば窓の左上の座標（隠していれば隠す前の位置）を、動かしていなければ None を返す。"""
        # つかむ前の位置から変わっていない回（つかんだだけ）は、動かしていないものとして扱う
        if self._drag_origin is not None and self.pos() != self._drag_origin:
            return self.pos()
        return None

    def _remember_drag_origin(self) -> None:
        """見出しの行をつかんだ回の、最初につかむ前の位置を控える（open で下ろす）。"""
        if self._drag_origin is None:
            self._drag_origin = self.pos()

    def _show_state(self, *, paused: bool) -> None:
        """状態の表示（印と文字）と、一時停止・再開のどちらのボタンを出すかを替える。"""
        self._state_label.setText("● 一時停止中" if paused else "● 録音中")
        self._state_label.setProperty("role", "paused" if paused else "recording")
        self._state_label.style().unpolish(self._state_label)
        self._state_label.style().polish(self._state_label)
        self._pause_button.setVisible(not paused)
        self._resume_button.setVisible(paused)

    def _refresh_clock(self) -> None:
        """経過時間のラベルを、貯めた経過（数えている間はストップウォッチの経過も足す）で描き直す。"""
        elapsed_ms = self._accumulated_ms + (self._stopwatch.elapsed() if self._running else 0)
        self._elapsed_label.setText(format_clock(elapsed_ms))

    def _tick(self) -> None:
        """経過時間と波形を描き直す（一時停止の間は止める）。"""
        if not self._running:
            return
        self._refresh_clock()
        gain = self._deps.get_settings().ui.wave_gain
        self._levels.append(min(self._deps.level() * gain, 1.0))
        self._waveform.update()
