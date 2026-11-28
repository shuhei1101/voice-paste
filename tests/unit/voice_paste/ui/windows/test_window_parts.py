"""ui/windows/window_parts.py（IconButton の __init__・set_label）の単体テスト。

画面を使用するため offscreen の QApplication（conftest の qapp）で動かす。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def test_icon_button_label(qapp: QApplication) -> None:
    """読み上げ名とツールチップに同じ文言を入れ、文字は出さない（正常系）。"""
    from voice_paste.ui.windows.window_parts import IconButton

    # 準備・実行
    button = IconButton("preset_remove_0", "trash", "ChatGPTを削除")

    # 検証
    assert button.objectName() == "preset_remove_0"
    assert button.accessibleName() == "ChatGPTを削除"
    assert button.toolTip() == "ChatGPTを削除"
    assert button.text() == ""
    assert button.size() == QSize(28, 28)
    assert button.minimumSize() == QSize(28, 28)
    assert button.maximumSize() == QSize(28, 28)


def test_icon_button_set_label(qapp: QApplication) -> None:
    """読み上げ名とツールチップを一緒に替える（正常系）。"""
    from voice_paste.ui.windows.window_parts import IconButton

    # 準備
    button = IconButton("preset_remove_0", "trash", "プリセット 1 件目を削除")

    # 実行
    button.set_label("ChatGPTを削除")

    # 検証
    assert button.accessibleName() == "ChatGPTを削除"
    assert button.toolTip() == "ChatGPTを削除"
