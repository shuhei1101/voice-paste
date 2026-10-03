"""窓を置く位置（設定のモニターの作業領域の、設定の位置）。"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget

from voice_paste.shared.settings import UiSettings

WINDOW_MARGIN_PX: int = 24
"""録音の画面を作業領域の端に置くときに空ける余白（論理ピクセル）。"""


def place_window(
    window_size: QSize,
    available: QRect,
    position: Literal["center", "top-left", "top-right", "bottom-left", "bottom-right"],
) -> QPoint:
    """作業領域の設定の位置に窓を置く左上の座標を返す。端に置くときは作業領域から余白だけ離す。"""
    left = available.left()
    top = available.top()
    right = left + available.width() - window_size.width()
    bottom = top + available.height() - window_size.height()
    center_x = left + (available.width() - window_size.width()) // 2
    center_y = top + (available.height() - window_size.height()) // 2
    match position:
        case "center":
            return QPoint(center_x, center_y)
        case "top-left":
            return QPoint(left + WINDOW_MARGIN_PX, top + WINDOW_MARGIN_PX)
        case "top-right":
            return QPoint(right - WINDOW_MARGIN_PX, top + WINDOW_MARGIN_PX)
        case "bottom-left":
            return QPoint(left + WINDOW_MARGIN_PX, bottom - WINDOW_MARGIN_PX)
        case "bottom-right":
            return QPoint(right - WINDOW_MARGIN_PX, bottom - WINDOW_MARGIN_PX)


def move_to_configured_position(window: QWidget, ui: UiSettings) -> None:
    """窓を、設定のモニター（カーソルのあるモニターか主のモニター）の設定の位置へ動かす。"""
    # カーソルのあるモニターに出す設定なら、そのモニターを引く（引けなければ主のモニター）
    screen = QGuiApplication.screenAt(QCursor.pos()) if ui.follow_cursor else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    window.adjustSize()
    window.move(place_window(window.size(), screen.availableGeometry(), ui.position))
