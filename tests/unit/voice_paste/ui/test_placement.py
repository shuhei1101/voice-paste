"""ui/placement.py（place_window）の単体テスト。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize


def test_place_window_when_center() -> None:
    """中央に置く（正常系）。"""
    from voice_paste.ui.placement import place_window

    # 実行
    point = place_window(QSize(400, 200), QRect(0, 0, 1920, 1040), "center")

    # 検証
    assert point == QPoint(760, 420)


def test_place_window_when_bottom_right() -> None:
    """右下に余白を空けて置く（正常系）。"""
    from voice_paste.ui.placement import place_window

    # 実行（余白 WINDOW_MARGIN_PX は 24: x = 1920 + 2560 - 400 - 24、y = 1400 - 200 - 24）
    point = place_window(QSize(400, 200), QRect(1920, 0, 2560, 1400), "bottom-right")

    # 検証
    assert point == QPoint(4056, 1176)
