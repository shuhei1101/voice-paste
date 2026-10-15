"""録音の画面と文字起こし中の表示が使う部品（見出しの行・つかむ印・名前の下にホットキーを出すボタン）。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QEnterEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from voice_paste.ui.style import theme_color
from voice_paste.ui.windows.settings_window import format_hotkey

BUTTON_PADDING_PX: tuple[int, int] = (12, 4)
"""ホットキーを持つボタンの、左右と上下の余白。"""

BUTTON_KEY_GAP_PX: int = 2
"""ホットキーを持つボタンの、名前とキーの間の幅。"""

GRIP_SIZE: tuple[int, int] = (12, 16)
"""つかむ印の幅と高さ。"""

GRIP_DOT_RADIUS_PX: float = 1.4
"""つかむ印の点の半径。"""

GRIP_COLUMNS: tuple[float, ...] = (3.0, 9.0)
GRIP_ROWS: tuple[float, ...] = (3.0, 8.0, 13.0)
"""つかむ印の点を置く列と段の座標（2 列 3 段）。"""


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


class HotkeyButton(QPushButton):
    """名前を 1 行目に、同じ操作のホットキーを枠で囲んだ等幅のキーで 2 行目に出すボタン。

    ボタンの大きさは、中の名前とキーが要る大きさから決める（QPushButton の sizeHint は中の部品を数えない）。
    ホットキーが空のときは名前だけを、上下の中央に出す。
    """

    def __init__(self, name: str, text: str, hotkey: str, *, tooltip: str | None = None) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setProperty("role", "hotkey_button")
        # 同じ行・同じ列のボタンと高さを揃えるため、行の高さまで伸ばす
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*BUTTON_PADDING_PX, *BUTTON_PADDING_PX)
        layout.setSpacing(BUTTON_KEY_GAP_PX)
        center = Qt.AlignmentFlag.AlignHCenter
        layout.addStretch(1)
        text_label = QLabel(text)
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(text_label, 0, center)
        # ホットキーが空のときは、名前だけを出す
        if hotkey:
            key_label = QLabel(format_hotkey(hotkey))
            key_label.setProperty("role", "keycap")
            key_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(key_label, 0, center)
        layout.addStretch(1)
        if tooltip:
            self.setToolTip(tooltip)

    def sizeHint(self) -> QSize:  # noqa: N802 Qt の名前
        """中の名前とキーが要る大きさ（枠の最小の高さを下回らない）を返す。"""
        return super().sizeHint().expandedTo(self.layout().sizeHint())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 Qt の名前
        """切れないよう、要る大きさを最小の大きさにする。"""
        return self.sizeHint()


def clear_layout(layout: QLayout) -> None:
    """レイアウトの中の部品を全て外して捨てる（外した分の大きさを数え直させる）。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # 親から外して隠し（捨てるまで描かれ続けない）、次のイベントで捨てる
            widget.setParent(None)
            widget.deleteLater()
    layout.invalidate()
