"""ui/windows/settings_edge_phrases.py（EdgePhrasePanel の set_phrases・collect・add_phrase・move_phrase・change_values）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
部品は画面設計の項目 ID（edge_phrase_text_{n}・edge_phrase_position_{n}・edge_phrase_empty）の objectName で引く。
欄は、objectName の前方一致で、画面に出ているものを名前の順で引く。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QAccessibleEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import EdgePhraseSettings
    from voice_paste.ui.windows.settings_edge_phrases import EdgePhrasePanel


@pytest.fixture
def open_panel(qapp: QApplication) -> Iterator[Callable[..., EdgePhrasePanel]]:
    """文言の一覧を入れた EdgePhrasePanel を出す関数を返す。出した部品はテストの後に隠す。"""
    from voice_paste.ui.windows.settings_edge_phrases import EdgePhrasePanel

    panels: list[EdgePhrasePanel] = []

    def _open(phrases: list[EdgePhraseSettings]) -> EdgePhrasePanel:
        """部品を作って一覧を入れ、画面に出す。"""
        panel = EdgePhrasePanel()
        panel.set_phrases(phrases)
        panel.show()
        panels.append(panel)
        return panel

    yield _open

    for panel in panels:
        panel.hide()


def _text_edits(panel: EdgePhrasePanel) -> list[QLineEdit]:
    """画面に出ている文言の欄を、名前の順で返す。"""
    found = panel.findChildren(QLineEdit, QRegularExpression("^edge_phrase_text_"))
    return sorted((edit for edit in found if edit.isVisible()), key=lambda edit: edit.objectName())


def _position_combos(panel: EdgePhrasePanel) -> list[QComboBox]:
    """画面に出ている位置の選択を、名前の順で返す。"""
    found = panel.findChildren(QComboBox, QRegularExpression("^edge_phrase_position_"))
    return sorted((box for box in found if box.isVisible()), key=lambda box: box.objectName())


def _is_empty_guide_visible(panel: EdgePhrasePanel) -> bool:
    """行が無いときの文（edge_phrase_empty）が画面に出ているか。"""
    guide = panel.findChild(QLabel, "edge_phrase_empty")
    assert guide is not None, "edge_phrase_empty の文が無い"
    return guide.isVisible()


# === collect ===


def test_edge_phrase_panel_collect(open_panel: Callable[..., EdgePhrasePanel]) -> None:
    """入れた行をそのまま集める（正常系）。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「チャンネル登録*」（end）と「えーと」（start））
    panel = open_panel(
        [
            EdgePhraseSettings(text="チャンネル登録*", position="end"),
            EdgePhraseSettings(text="えーと", position="start"),
        ]
    )

    # 実行
    collected = panel.collect()

    # 検証
    assert collected == [
        {"text": "チャンネル登録*", "position": "end"},
        {"text": "えーと", "position": "start"},
    ]
    assert [box.currentText() for box in _position_combos(panel)] == ["文末", "文頭"]


# === add_phrase ===


def test_edge_phrase_panel_add_phrase(open_panel: Callable[..., EdgePhrasePanel]) -> None:
    """足した行は文末で始まる（正常系）。"""
    # 準備（空の一覧では行が無いときの文が出ている）
    panel = open_panel([])
    changed_count: list[int] = []
    panel.changed.connect(lambda: changed_count.append(1))
    assert _is_empty_guide_visible(panel)

    # 実行
    panel.add_phrase()

    # 検証
    assert panel.collect() == [{"text": "", "position": "end"}]
    assert changed_count == [1]
    assert not _is_empty_guide_visible(panel)


# === move_phrase ===


def test_edge_phrase_panel_move_phrase(
    open_panel: Callable[..., EdgePhrasePanel], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alt+↑ で行を上へ動かし、フォーカスを動かした行に残す（正常系）。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（A・B の 2 行を入れ、読み上げに渡すイベントを控える）
    announced: list[QAccessibleEvent] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", announced.append)
    panel = open_panel([EdgePhraseSettings(text="A"), EdgePhraseSettings(text="B")])

    # 実行（B の文言の欄に Alt+↑ を送る）
    QTest.keyClick(_text_edits(panel)[1], Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)

    # 検証
    assert [row["text"] for row in panel.collect()] == ["B", "A"]
    assert panel.focusWidget() is _text_edits(panel)[0]
    assert [
        event.message() for event in announced if isinstance(event, QAccessibleAnnouncementEvent)
    ] == ["1 行目へ動かしました"]


def test_edge_phrase_panel_move_phrase_when_edge(
    open_panel: Callable[..., EdgePhrasePanel],
) -> None:
    """先頭を上へ・末尾を下へは何もしない（正常系）。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（A・B の 2 行）
    panel = open_panel([EdgePhraseSettings(text="A"), EdgePhraseSettings(text="B")])
    changed_count: list[int] = []
    panel.changed.connect(lambda: changed_count.append(1))

    # 実行（先頭を上へ・末尾を下へ）
    panel.move_phrase(0, -1)
    panel.move_phrase(1, 1)

    # 検証
    assert [row["text"] for row in panel.collect()] == ["A", "B"]
    assert changed_count == []


# === change_values ===


def test_edge_phrase_panel_change_values_when_moved(
    open_panel: Callable[..., EdgePhrasePanel],
) -> None:
    """並べ替えると行の値は変わらず、並びの値だけが変わる（正常系）。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（A・B・C の 3 行）
    panel = open_panel(
        [
            EdgePhraseSettings(text="A"),
            EdgePhraseSettings(text="B"),
            EdgePhraseSettings(text="C"),
        ]
    )
    before = panel.change_values()
    assert before["edge_phrases.order"] is True

    # 実行（A を 1 つ下へ動かす）
    panel.move_phrase(0, 1)

    # 検証
    assert panel.change_values() == {**before, "edge_phrases.order": False}
