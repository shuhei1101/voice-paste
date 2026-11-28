"""録音の画面・文字起こし中の表示・設定画面が使用する部品（見出しの行・つかむマーカー・名前の下にホットキーを出すボタン・アイコンのボタン）。"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QEnterEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from voice_paste.ui.style import theme_color

BUTTON_PADDING_PX: tuple[int, int] = (12, 4)
"""ホットキーを持つボタンの、左右と上下の余白。"""

BUTTON_KEY_GAP_PX: int = 2
"""ホットキーを持つボタンの、名前とキーの間の幅。"""

GRIP_SIZE: tuple[int, int] = (12, 16)
"""つかむマーカーの幅と高さ。"""

GRIP_DOT_RADIUS_PX: float = 1.4
"""つかむマーカーの点の半径。"""

GRIP_COLUMNS: tuple[float, ...] = (3.0, 9.0)
GRIP_ROWS: tuple[float, ...] = (3.0, 8.0, 13.0)
"""つかむマーカーの点を置く列と行の座標（2 列 3 行）。"""

ICON_BUTTON_SIZE_PX: int = 28
"""設定画面の行の操作のアイコンのボタンの幅と高さ（同じ行の入力欄の高さにそろえる）。"""

ICON_PEN_PX: float = 1.6
"""アイコンのボタンに描く線の太さ。"""

ICON_GLYPH_HALF_PX: float = 6.0
"""アイコンを描く正方形の、中心から端までの長さ。"""

IconName = Literal["trash", "arrow_up", "arrow_down", "x"]
"""アイコンのボタンが描くアイコンの種類。"""


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
        """かざしたら、つかむマーカーを濃くするために子を描き直す。"""
        super().enterEvent(event)
        for child in self.findChildren(GripIcon):
            child.update()

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 Qt の名前
        """外れたら、つかむマーカーを戻すために子を描き直す。"""
        super().leaveEvent(event)
        for child in self.findChildren(GripIcon):
            child.update()


class GripIcon(QWidget):
    """窓をつかめることを示す、点を 2 列 3 行に並べたマーカー。見出しの行にかざしている間は濃くする。"""

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
            # 設定画面の部品もこのファイルを読み込むため、設定画面は使用する時点で読み込む
            from voice_paste.ui.windows.settings_window import format_hotkey

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


class IconButton(QPushButton):
    """設定画面の行の操作（削除・上へ・下へ・外す）に配置する、アイコンだけのボタン。

    アイコンは画像を持たず線で描き、読み上げ名と同じ文言をツールチップに出す。
    押せないとき（setEnabled(False) か property("inactive") が True）は薄い色で描く。
    """

    def __init__(self, name: str, icon: IconName, label: str) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setFixedSize(ICON_BUTTON_SIZE_PX, ICON_BUTTON_SIZE_PX)
        self._icon: IconName = icon
        self.set_label(label)

    def set_label(self, label: str) -> None:
        """読み上げ名とツールチップの文言を替える。"""
        self.setAccessibleName(label)
        self.setToolTip(label)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 Qt の名前
        """面と枠を描いた後、アイコンの線を描く。"""
        super().paintEvent(event)
        muted = not self.isEnabled() or bool(self.property("inactive"))
        pen = QPen(theme_color("text_muted" if muted else "text"), ICON_PEN_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, half = self.width() / 2, self.height() / 2, ICON_GLYPH_HALF_PX
        # アイコンの種類ごとに線を描く
        if self._icon == "trash":
            # ごみ箱: ふたの横線・取っ手・下すぼまりの胴・中の縦線 2 本
            painter.drawLine(QLineF(cx - half, cy - half + 2, cx + half, cy - half + 2))
            painter.drawRect(QRectF(cx - 2, cy - half, 4, 2))
            body_top, body_bottom = cy - half + 4, cy + half
            painter.drawLine(QLineF(cx - half + 1.5, body_top, cx - half + 2.5, body_bottom))
            painter.drawLine(QLineF(cx - half + 2.5, body_bottom, cx + half - 2.5, body_bottom))
            painter.drawLine(QLineF(cx + half - 2.5, body_bottom, cx + half - 1.5, body_top))
            painter.drawLine(QLineF(cx - 1.5, body_top + 2, cx - 1.5, body_bottom - 2))
            painter.drawLine(QLineF(cx + 1.5, body_top + 2, cx + 1.5, body_bottom - 2))
        elif self._icon in ("arrow_up", "arrow_down"):
            # 上下の矢印: 縦の軸と、先端の折れ線
            tip, tail = (cy - half, cy + half) if self._icon == "arrow_up" else (cy + half, cy - half)
            wing = tip + (half * 0.8 if self._icon == "arrow_up" else -half * 0.8)
            painter.drawLine(QLineF(cx, tail, cx, tip))
            painter.drawLine(QLineF(cx - half * 0.8, wing, cx, tip))
            painter.drawLine(QLineF(cx, tip, cx + half * 0.8, wing))
        else:
            # ×: 斜めの 2 本
            painter.drawLine(QLineF(cx - half, cy - half, cx + half, cy + half))
            painter.drawLine(QLineF(cx + half, cy - half, cx - half, cy + half))


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
