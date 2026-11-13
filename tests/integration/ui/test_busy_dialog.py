"""画面設計「処理中のダイアログ」を元にした結合テスト。

ダイアログは open で開いてすぐ戻る（exec で止めない）ため、出たダイアログを項目 ID（busy_dialog）で引いて操作する。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from tests.integration.ui.helpers import Ui, dispose_windows_since, find, top_level_windows



def _dialogs() -> list[QMessageBox]:
    """今出ている処理中のダイアログを並べる。"""
    return [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, QMessageBox)
        and widget.objectName() == "busy_dialog"
        and widget.isVisible()
    ]


@pytest.fixture(autouse=True)
def close_dialogs(qapp: QApplication) -> Iterator[None]:
    """テストの後に、出たままの処理中のダイアログを閉じて破棄する。"""
    before = top_level_windows()
    yield
    dispose_windows_since(before)


def _shown_dialog(reason: str | None = None) -> QMessageBox:
    """処理中のダイアログを出して、出たダイアログを返す（理由を省くと API の録音の処理中）。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_API, show_busy_dialog

    show_busy_dialog(reason or BUSY_REASON_API)
    dialogs = _dialogs()
    assert len(dialogs) == 1
    return dialogs[0]


# === busy_dialog ===


def test_busy_dialog_visible_when_busy(make_ui: Callable[..., Ui]) -> None:
    """busy の知らせを受けたとき、ダイアログを出す（表示条件）。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified("busy", None)

    # 検証
    assert len(_dialogs()) == 1


def test_busy_dialog_properties() -> None:
    """窓のタイトルは voice-paste で、「常に手前に表示」のモーダル。"""
    # 実行
    dialog = _shown_dialog()

    # 検証
    assert dialog.windowTitle() == "voice-paste"
    assert dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_busy_dialog_when_shown_twice() -> None:
    """既に出ていれば、もう 1 つは出さず前面に出すだけにする。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_API, show_busy_dialog

    # 準備
    _shown_dialog()

    # 実行
    show_busy_dialog(BUSY_REASON_API)

    # 検証
    assert len(_dialogs()) == 1


def test_busy_dialog_when_reopened() -> None:
    """閉じた後は、次の知らせでまた出る。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_API, show_busy_dialog

    # 準備
    _shown_dialog().close()
    QApplication.processEvents()

    # 実行
    show_busy_dialog(BUSY_REASON_API)

    # 検証
    assert len(_dialogs()) == 1


# === busy_title・busy_body・busy_body_finishing ===


def test_busy_title() -> None:
    """始められないことを「録音を開始できませんでした」と伝える。"""
    # 実行
    dialog = _shown_dialog()

    # 検証
    assert dialog.text() == "録音を開始できませんでした"


BODY_API = (
    "ほかのシステムから始めた録音を処理しています。"
    "終わってから、もう一度録音開始のホットキーを押してください。"
)
"""API の録音の処理中の本文。"""

BODY_FINISHING = (
    "前の録音を文字に起こして届けています。"
    "終わってから、もう一度録音開始のホットキーを押してください。"
)
"""前の録音の終了の処理中の本文。"""


def test_busy_title_when_finishing() -> None:
    """前の録音の終了の処理中でも、見出しは同じ。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_FINISHING

    # 実行
    dialog = _shown_dialog(BUSY_REASON_FINISHING)

    # 検証
    assert dialog.text() == "録音を開始できませんでした"


def test_busy_body() -> None:
    """処理中の録音の入口が api なら、API の録音の処理中の理由と次にすることを伝える。"""
    # 実行
    dialog = _shown_dialog()

    # 検証
    assert dialog.informativeText() == BODY_API


def test_busy_body_finishing() -> None:
    """ホットキー・トレイの録音の確定後の処理中なら、前の録音の終了の処理中の理由と次にすることを伝える。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_FINISHING

    # 実行
    dialog = _shown_dialog(BUSY_REASON_FINISHING)

    # 検証
    assert dialog.informativeText() == BODY_FINISHING


@pytest.mark.parametrize(
    ("reason", "body"),
    [("api", BODY_API), ("finishing", BODY_FINISHING)],
    ids=["api", "finishing"],
)
def test_busy_body_when_notified(make_ui: Callable[..., Ui], reason: str, body: str) -> None:
    """busy の知らせの理由（detail）に合わせた本文を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified("busy", reason)

    # 検証
    dialogs = _dialogs()
    assert len(dialogs) == 1
    assert dialogs[0].informativeText() == body


def test_busy_body_when_shown_twice_with_other_reason() -> None:
    """既に出ているときに別の理由で知らせを受けたら、本文を今の理由に替える。"""
    from voice_paste.ui.windows.busy_dialog import BUSY_REASON_FINISHING, show_busy_dialog

    # 準備
    _shown_dialog()

    # 実行
    show_busy_dialog(BUSY_REASON_FINISHING)

    # 検証
    dialogs = _dialogs()
    assert len(dialogs) == 1
    assert dialogs[0].informativeText() == BODY_FINISHING


# === close_button ===


def test_close_button_label() -> None:
    """閉じるボタンは「閉じる」で、最初のフォーカス（既定のボタン）を置く。"""
    # 実行
    dialog = _shown_dialog()

    # 検証
    button = find(dialog, QPushButton, "close_button")
    assert button.text() == "閉じる"
    assert dialog.defaultButton() is button


def test_close_button_action() -> None:
    """閉じるボタンを押すと、ダイアログを閉じる。"""
    # 準備
    dialog = _shown_dialog()

    # 実行
    QTest.mouseClick(find(dialog, QPushButton, "close_button"), Qt.MouseButton.LeftButton)

    # 検証
    assert _dialogs() == []


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Escape], ids=["enter", "escape"])
def test_busy_dialog_closes_by_key(key: Qt.Key) -> None:
    """Enter・Esc でも閉じる。"""
    # 準備
    dialog = _shown_dialog()

    # 実行
    QTest.keyClick(dialog, key)

    # 検証
    assert _dialogs() == []
