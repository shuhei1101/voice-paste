"""ui/windows/settings_hints.py（HintPresetPanel の set_presets・collect・add_preset・add_word・hint_length と並べ替え）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
部品は画面設計の項目 ID（hint_preset_enabled_{n}・hint_preset_name_{n}・hint_word_{n}_{m}・hint_preset_down_{n}・hint_length・hint_preset_empty）の objectName で引く。
欄とボタンは、objectName の前方一致で、画面に出ているものを名前の順で引く。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QProgressBar, QWidget

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import HintPresetSettings
    from voice_paste.ui.windows.settings_hints import HintPresetPanel

OVER_LIMIT_WORD_CHARS = 86
"""日本語 86 文字 = 258 バイトになる語の文字数。"""


@pytest.fixture
def open_panel(qapp: QApplication) -> Iterator[Callable[..., HintPresetPanel]]:
    """プリセットの一覧を入れた HintPresetPanel を出す関数を返す。出した部品はテストの後に隠す。"""
    from voice_paste.ui.windows.settings_hints import HintPresetPanel

    panels: list[HintPresetPanel] = []

    def _open(presets: list[HintPresetSettings]) -> HintPresetPanel:
        """部品を作って一覧を入れ、画面に出す。"""
        panel = HintPresetPanel()
        panel.set_presets(presets)
        panel.show()
        panels.append(panel)
        return panel

    yield _open

    for panel in panels:
        panel.hide()


def _visible_edits(panel: HintPresetPanel, prefix: str) -> list[QLineEdit]:
    """画面に出ている、objectName が prefix で始まる文字の欄を、名前の順で返す。"""
    found = panel.findChildren(QLineEdit, QRegularExpression(f"^{prefix}"))
    return sorted((edit for edit in found if edit.isVisible()), key=lambda edit: edit.objectName())


def _visible_buttons(panel: HintPresetPanel, prefix: str) -> list[QAbstractButton]:
    """画面に出ている、objectName が prefix で始まるボタンを、名前の順で返す。"""
    found = panel.findChildren(QAbstractButton, QRegularExpression(f"^{prefix}"))
    return sorted(
        (button for button in found if button.isVisible()), key=lambda button: button.objectName()
    )


def _length_text(panel: HintPresetPanel) -> str:
    """有効なヒントの長さの行（hint_length）に出ている文字を、続けて返す。"""
    row = panel.findChild(QWidget, "hint_length")
    assert row is not None, "hint_length の行が無い"
    parts: list[str] = []
    if isinstance(row, QLabel):
        parts.append(row.text())
    if isinstance(row, QProgressBar):
        parts.append(row.text())
    parts.extend(label.text() for label in row.findChildren(QLabel))
    parts.extend(bar.text() for bar in row.findChildren(QProgressBar))
    return " ".join(parts)


def _is_empty_guide_visible(panel: HintPresetPanel) -> bool:
    """プリセットが無いときの案内（hint_preset_empty）が画面に出ているか。"""
    guide = panel.findChild(QLabel, "hint_preset_empty")
    assert guide is not None, "hint_preset_empty の案内が無い"
    return guide.isVisible()


# === collect ===


def test_hint_preset_panel_collect(open_panel: Callable[..., HintPresetPanel]) -> None:
    """入れたプリセットをそのまま集める（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings

    # 準備（有効な「開発」（語 voice-paste・Whisper）と無効な「会議」（語 議事録））
    panel = open_panel(
        [
            HintPresetSettings(name="開発", words=["voice-paste", "Whisper"]),
            HintPresetSettings(name="会議", words=["議事録"], enabled=False),
        ]
    )

    # 実行
    collected = panel.collect()

    # 検証
    assert [preset["name"] for preset in collected] == ["開発", "会議"]
    assert collected[0]["words"] == ["voice-paste", "Whisper"]
    assert collected[0]["enabled"] is True
    assert collected[1]["words"] == ["議事録"]
    assert collected[1]["enabled"] is False


def test_hint_preset_panel_move(open_panel: Callable[..., HintPresetPanel]) -> None:
    """下へで並びを入れ替える（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings

    # 準備
    panel = open_panel([HintPresetSettings(name="A"), HintPresetSettings(name="B")])

    # 実行（A の「下へ」を押す）
    _visible_buttons(panel, "hint_preset_down_")[0].click()

    # 検証
    assert [preset["name"] for preset in panel.collect()] == ["B", "A"]


# === add_preset ===


def test_hint_preset_panel_add_preset(open_panel: Callable[..., HintPresetPanel]) -> None:
    """足したプリセットは有効で始まる（正常系）。"""
    # 準備（空の一覧では案内が出ている）
    panel = open_panel([])
    changed_count: list[int] = []
    panel.changed.connect(lambda: changed_count.append(1))
    assert _is_empty_guide_visible(panel)

    # 実行
    panel.add_preset()

    # 検証
    assert panel.collect() == [{"name": "", "words": [], "enabled": True}]
    assert changed_count == [1]
    assert not _is_empty_guide_visible(panel)


# === hint_length ===


def test_hint_preset_panel_hint_length(open_panel: Callable[..., HintPresetPanel]) -> None:
    """切り替えと入力で長さを数え直す（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings

    # 準備（有効な「開発」（語 abc）と無効な「会議」（語 議事録））
    panel = open_panel(
        [
            HintPresetSettings(name="開発", words=["abc"]),
            HintPresetSettings(name="会議", words=["議事録"], enabled=False),
        ]
    )
    before = panel.hint_length()

    # 実行（「会議」を有効に切り替える）
    _visible_buttons(panel, "hint_preset_enabled_")[1].click()

    # 検証（切り替える前は abc の 3、切り替えた後は abc、議事録 の 15）
    assert before == 3
    assert panel.hint_length() == 15
    assert "15 / 222 バイト" in _length_text(panel)


def test_hint_preset_panel_hint_length_when_over(
    open_panel: Callable[..., HintPresetPanel],
) -> None:
    """上限を超えたら超過を文字で添える（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings

    # 準備（有効なプリセットにつないだ長さが 258 バイトになる語）
    word = "あ" * OVER_LIMIT_WORD_CHARS

    # 実行
    panel = open_panel([HintPresetSettings(name="開発", words=[word])])

    # 検証
    assert panel.hint_length() == 258
    assert "258 / 222 バイト（36 バイト超過）" in _length_text(panel)


def test_hint_preset_panel_hint_length_when_unvalidated(
    open_panel: Callable[..., HintPresetPanel],
) -> None:
    """足した直後と、区切りを含む語を入れた直後にも長さを数え直せる（正常系）。"""
    # 準備（空の一覧で add_preset を呼ぶ。名前と語が空）
    panel = open_panel([])
    panel.add_preset()
    after_add = panel.hint_length()

    # 実行（add_word で足した語の欄に「A、B」を入れる）
    panel.add_word(0)
    _visible_edits(panel, r"hint_word_\d")[0].setText("A、B")

    # 検証（例外が出ず、足した直後は 0、入れた後は A、B の 5）
    assert after_add == 0
    assert panel.hint_length() == 5
