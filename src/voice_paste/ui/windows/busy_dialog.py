"""処理中のダイアログ（API から始めた録音の処理中に録音開始のホットキーを押したとき）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

WINDOW_TITLE: str = "voice-paste"
"""ダイアログの窓のタイトル。"""

HEADING: str = "録音を開始できませんでした"
"""始められないことを伝える見出し。"""

BODY: str = (
    "ほかのシステムから始めた録音を処理しています。終わってから、もう一度録音開始のホットキーを押してください。"
)
"""理由と次にすることを伝える本文。"""

CLOSE_TEXT: str = "閉じる"
"""閉じるボタンの文言。"""

_open_dialog: QMessageBox | None = None
"""今出ているダイアログ（無ければ None）。二重に出さないために持つ。"""


def show_busy_dialog() -> None:
    """「常に手前に表示」のダイアログで、処理中のため録音を始められないことを知らせる。既に出ていれば前面に出すだけにする。

    モーダルを open で開いてすぐ戻る（exec でメインスレッドを止めない）。
    """
    global _open_dialog  # noqa: PLW0603 二重に出さないため、出ているダイアログを 1 つだけ持つ

    # 既に出ていれば、前面に出すだけにする
    if _open_dialog is not None:
        _open_dialog.raise_()
        _open_dialog.activateWindow()
        return

    dialog = QMessageBox()
    dialog.setObjectName("busy_dialog")
    dialog.setWindowTitle(WINDOW_TITLE)
    dialog.setIcon(QMessageBox.Icon.NoIcon)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setText(HEADING)
    dialog.setInformativeText(BODY)
    close_button = dialog.addButton(CLOSE_TEXT, QMessageBox.ButtonRole.AcceptRole)
    close_button.setObjectName("close_button")
    # Enter・Esc のどちらでも閉じる
    dialog.setDefaultButton(close_button)
    dialog.setEscapeButton(close_button)
    dialog.finished.connect(_forget_dialog)
    _open_dialog = dialog
    dialog.open()


def _forget_dialog() -> None:
    """ダイアログが閉じたら、持っているダイアログを手放す。"""
    global _open_dialog  # noqa: PLW0603 出ているダイアログを手放す
    _open_dialog = None
