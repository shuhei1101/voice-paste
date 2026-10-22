"""チェックボックスの箱・ラジオボタンの丸を、Qt の既定のスタイルに任せず theme_color の色で描くスタイル。"""

from __future__ import annotations

from typing import override

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleOption, QWidget

from voice_paste.ui.style import load_tokens, theme_color

BOX_RADIUS: float = 4.0
"""チェックボックスの箱の角の丸め（px）。"""

LINE_WIDTH: float = 1.0
"""箱・丸の縁の線の太さ（px）。"""

CHECK_VIEWBOX: float = 12.0
"""チェックの形を決めた正方形の一辺。"""

CHECK_RATIO: float = 0.75
"""チェックを描く正方形の一辺の、箱の一辺に対する割合（16px の箱に 12px）。"""

CHECK_POINTS: tuple[tuple[float, float], ...] = ((2.5, 6.2), (4.8, 8.5), (9.5, 3.5))
"""チェックの折れ線の頂点（CHECK_VIEWBOX の正方形の中の位置）。"""

CHECK_STROKE: float = 1.8
"""チェックの線の太さ（CHECK_VIEWBOX の正方形の中での太さ）。"""

INDICATOR_METRICS: frozenset[QStyle.PixelMetric] = frozenset(
    {
        QStyle.PixelMetric.PM_IndicatorWidth,
        QStyle.PixelMetric.PM_IndicatorHeight,
        QStyle.PixelMetric.PM_ExclusiveIndicatorWidth,
        QStyle.PixelMetric.PM_ExclusiveIndicatorHeight,
    }
)
"""チェックボックスの箱とラジオボタンの丸の幅・高さを問い合わせる大きさの種類。"""


class IndicatorStyle(QProxyStyle):
    """チェックボックスの箱とラジオボタンの丸を、状態に合わせた色で描くスタイル。印でない要素は包んだスタイルへ渡す。"""

    @override
    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        """チェックボックス・ラジオボタンの印を描き、ほかの要素は包んだスタイルへ渡す。"""
        # 要素で分ける
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            self._draw_check_box(option, painter)
        elif element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
            self._draw_radio_button(option, painter)
        else:
            # 印でない要素: 包んだスタイルが描く
            super().drawPrimitive(element, option, painter, widget)

    @override
    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        """印の幅・高さは tokens.toml の shape.indicator にし、ほかの大きさは包んだスタイルの値を返す。"""
        if metric in INDICATOR_METRICS:
            return int(load_tokens()["shape"]["indicator"])
        return super().pixelMetric(metric, option, widget)

    def _draw_check_box(self, option: QStyleOption, painter: QPainter) -> None:
        """角を丸めた箱を描く。オンなら塗ってチェックを重ねる。"""
        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        checked = bool(state & QStyle.StateFlag.State_On)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        box = self._box(option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if checked:
            # オン: 使えるなら accent_fg、使えないなら border で塗る
            fill = theme_color("accent_fg" if enabled else "border")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, BOX_RADIUS, BOX_RADIUS)
            self._draw_check(painter, box, theme_color("surface" if enabled else "text_muted"))
        else:
            # オフ: sunken で塗り、線で囲む（使えなければ border、マウスを重ねていれば accent_fg）
            painter.setPen(QPen(self._edge_color(enabled=enabled, hovered=hovered), LINE_WIDTH))
            painter.setBrush(theme_color("sunken"))
            painter.drawRoundedRect(box, BOX_RADIUS, BOX_RADIUS)
        painter.restore()

    def _draw_radio_button(self, option: QStyleOption, painter: QPainter) -> None:
        """丸を描く。選んでいれば中に点を描く。"""
        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        checked = bool(state & QStyle.StateFlag.State_On)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        circle = self._box(option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if checked:
            # 選んだ: 線を accent_fg にする（使えなければ border）。使えなければ丸の中を塗らない
            edge = theme_color("accent_fg" if enabled else "border")
            painter.setPen(QPen(edge, LINE_WIDTH))
            painter.setBrush(theme_color("sunken") if enabled else Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle)
            # 中心に点を描く（使えなければ text_muted）
            dot = float(load_tokens()["shape"]["indicator_dot"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme_color("accent_fg" if enabled else "text_muted"))
            painter.drawEllipse(circle.center(), dot / 2, dot / 2)
        else:
            # 選んでいない: sunken で塗り、線で囲む（使えなければ border、マウスを重ねていれば accent_fg）
            painter.setPen(QPen(self._edge_color(enabled=enabled, hovered=hovered), LINE_WIDTH))
            painter.setBrush(theme_color("sunken"))
            painter.drawEllipse(circle)
        painter.restore()

    @staticmethod
    def _box(option: QStyleOption) -> QRectF:
        """描く範囲を、縁の線が範囲の内側に収まるよう半分の太さだけ縮めて返す。"""
        half = LINE_WIDTH / 2
        return QRectF(option.rect).adjusted(half, half, -half, -half)

    @staticmethod
    def _edge_color(*, enabled: bool, hovered: bool) -> QColor:
        """オフの箱・選んでいない丸の縁の色を返す。"""
        if not enabled:
            return theme_color("border")
        return theme_color("accent_fg" if hovered else "text_muted")

    @staticmethod
    def _draw_check(painter: QPainter, box: QRectF, color: QColor) -> None:
        """箱の中央にチェック（折れ線）を描く。"""
        scale = box.width() * CHECK_RATIO / CHECK_VIEWBOX
        origin = box.center() - QPointF(CHECK_VIEWBOX, CHECK_VIEWBOX) * scale / 2
        path = QPainterPath()
        for index, (x, y) in enumerate(CHECK_POINTS):
            point = origin + QPointF(x, y) * scale
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        pen = QPen(color, CHECK_STROKE * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
