"""処理中のダイアログ（API から始めた録音の処理中か、前の録音の終了の処理中に録音開始のホットキーを押したとき）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

WINDOW_TITLE: str = "voice-paste"
"""ダイアログの窓のタイトル。"""

HEADING: str = "録音を開始できませんでした"
"""始められないことを伝える見出し。"""

BUSY_REASON_API: str = "api"
"""録音を始められない理由のうち、API から始めた録音の処理中。busy の通知の detail に使う。"""

BUSY_REASON_FINISHING: str = "finishing"
"""録音を始められない理由のうち、ホットキー・トレイから始めた録音の確定後の文字起こし中・届け中。busy の通知の detail に使う。"""

BODY: str = (
    "ほかのシステムから始めた録音を処理しています。終わってから、もう一度録音開始のホットキーを押してください。"
)
"""API の録音の処理中の、理由と次にすることを伝える本文。"""

BODY_FINISHING: str = (
    "前の録音を文字に起こして届けています。終わってから、もう一度録音開始のホットキーを押してください。"
)
"""前の録音の終了の処理中の、理由と次にすることを伝える本文。"""

CLOSE_TEXT: str = "閉じる"
"""閉じるボタンの文言。"""

_open_dialog: QMessageBox | None = None
"""今出ているダイアログ（無ければ None）。二重に出さないために持つ。"""


def show_busy_dialog(reason: str | None) -> None:
    """「常に手前に表示」のダイアログで、録音を始められないことを理由ごとの本文で知らせる。既に出ていれば本文を今の理由に替えて前面に出す。

    reason は BUSY_REASON_API か BUSY_REASON_FINISHING（busy の通知の detail）。それ以外は BUSY_REASON_API として扱う。

    モーダルを open で開いてすぐ戻る（exec でメインスレッドを止めない）。
    """
    global _open_dialog  # noqa: PLW0603 二重に出さないため、出ているダイアログを 1 つだけ持つ

    body = BODY_FINISHING if reason == BUSY_REASON_FINISHING else BODY

    # 既に出ていれば、本文を今の理由に替えて前面に出す
    if _open_dialog is not None:
        _open_dialog.setInformativeText(body)
        _open_dialog.raise_()
        _open_dialog.activateWindow()
        return

    dialog = QMessageBox()
    dialog.setObjectName("busy_dialog")
    dialog.setWindowTitle(WINDOW_TITLE)
    dialog.setIcon(QMessageBox.Icon.NoIcon)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setText(HEADING)
    dialog.setInformativeText(body)
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
