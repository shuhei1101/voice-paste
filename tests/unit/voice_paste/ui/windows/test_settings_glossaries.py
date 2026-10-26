"""ui/windows/settings_glossaries.py（GlossaryPanel の set_glossaries・collect・collect_presets・active_preset_name・changed_rows・change_values・mark_saved・add_glossary・add_glossary_preset、find_glossary_row_errors）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
行を読む関数と足す用語集の場所を決める関数は Mock に差し替える。
部品は画面設計の項目 ID（glossary_pick_{n}・glossary_count_{n}・glossary_remove_{n}・glossary_preset_pick_{n}・glossary_preset_active_{n} など）の objectName で引く。
行の表に出ている欄は、objectName の前方一致で、画面に出ているものを名前の順で引く。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings
    from voice_paste.shared.types import GlossaryEntry
    from voice_paste.ui.windows.settings_glossaries import GlossaryPanel

UNREADABLE_REASON = "文字コードが UTF-8 ではありません"
"""読めない用語集の CSV の理由として、行を読む関数が送出する文言。"""


@dataclass
class Opened:
    """開いた用語集の部品と、渡した Mock。"""

    panel: GlossaryPanel
    read_glossary: MagicMock
    new_glossary_path: MagicMock
    new_path: Path


@pytest.fixture
def open_panel(qapp: QApplication, tmp_path: Path) -> Iterator[Callable[..., Opened]]:
    """用語集の一覧と行を指定して GlossaryPanel を作り、一覧を入れて出す関数を返す。出した部品はテストの後に隠す。"""
    from voice_paste.ui.windows.settings_glossaries import GlossaryPanel

    panels: list[GlossaryPanel] = []

    def _open(
        glossaries: list[GlossarySettings],
        rows: Mapping[Path, list[GlossaryEntry] | GlossaryReadError],
        *,
        presets: list[GlossaryPresetSettings] | None = None,
        active_preset: str | None = None,
    ) -> Opened:
        """場所の行を返す（GlossaryReadError を渡した場所は送出する）関数で部品を作り、一覧を入れる。

        presets を渡さなければ、1 件目の用語集だけを使う「既定」の 1 件にする。
        """
        from voice_paste.shared.settings import GlossaryPresetSettings

        def read(path: Path) -> list[GlossaryEntry]:
            """場所の行を返す。GlossaryReadError を渡した場所は送出する。"""
            result = rows[path]
            if isinstance(result, Exception):
                raise result
            return list(result)

        new_path = tmp_path / "glossaries" / "glossary_1.csv"
        read_glossary = MagicMock(side_effect=read)
        new_glossary_path = MagicMock(return_value=new_path)
        panel = GlossaryPanel(read_glossary, new_glossary_path)
        opened_presets = presets or [
            GlossaryPresetSettings(name="既定", glossaries=[glossaries[0].name])
        ]
        panel.set_glossaries(
            glossaries, opened_presets, active_preset or opened_presets[0].name
        )
        panel.show()
        panels.append(panel)
        return Opened(
            panel=panel,
            read_glossary=read_glossary,
            new_glossary_path=new_glossary_path,
            new_path=new_path,
        )

    yield _open

    for panel in panels:
        panel.hide()


def _button(panel: GlossaryPanel, name: str) -> QAbstractButton:
    """objectName が name のボタンを返す。"""
    button = panel.findChild(QAbstractButton, name)
    assert button is not None, f"{name} のボタンが無い"
    return button


def _label(panel: GlossaryPanel, name: str) -> QLabel:
    """objectName が name の文字の表示を返す。"""
    label = panel.findChild(QLabel, name)
    assert label is not None, f"{name} の表示が無い"
    return label


def _visible_edits(panel: GlossaryPanel, prefix: str) -> list[QLineEdit]:
    """画面に出ている、objectName が prefix で始まる文字の欄を、名前の順で返す。"""
    found = panel.findChildren(QLineEdit, QRegularExpression(f"^{prefix}"))
    return sorted((edit for edit in found if edit.isVisible()), key=lambda edit: edit.objectName())


def _visible_buttons(panel: GlossaryPanel, prefix: str) -> list[QAbstractButton]:
    """画面に出ている、objectName が prefix で始まるボタンを、名前の順で返す。"""
    found = panel.findChildren(QAbstractButton, QRegularExpression(f"^{prefix}"))
    return sorted(
        (button for button in found if button.isVisible()), key=lambda button: button.objectName()
    )


def _two_glossaries(tmp_path: Path) -> tuple[GlossarySettings, GlossarySettings]:
    """「yogo」「会議用」の 2 件の用語集（場所は一時フォルダの下）を返す。"""
    from voice_paste.shared.settings import GlossarySettings

    return (
        GlossarySettings(name="yogo", path=tmp_path / "yogo.csv"),
        GlossarySettings(name="会議用", path=tmp_path / "meeting.csv"),
    )


def _two_presets() -> list[GlossaryPresetSettings]:
    """「既定」（["yogo"]）と「会議」（["会議用", "yogo"]）の 2 件の用語集のプリセットを返す。"""
    from voice_paste.shared.settings import GlossaryPresetSettings

    return [
        GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
        GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"]),
    ]


def _combo(panel: GlossaryPanel, name: str) -> QComboBox:
    """objectName が name の選択の欄を返す。"""
    combo = panel.findChild(QComboBox, name)
    assert combo is not None, f"{name} の選択の欄が無い"
    return combo


def _combo_texts(combo: QComboBox) -> list[str]:
    """選択の欄の選択肢の文字を、並びの順で返す。"""
    return [combo.itemText(index) for index in range(combo.count())]


def _used_glossary_names(panel: GlossaryPanel) -> list[str]:
    """使う用語集の表に出ている用語集の名前を、表の順で返す（外すボタンの読み上げ名「{用語集}を外す」から引く）。"""
    buttons = _visible_buttons(panel, "glossary_preset_glossary_remove_")
    return [button.accessibleName().removesuffix("を外す") for button in buttons]


def _add_preset_glossary(panel: GlossaryPanel, name: str) -> None:
    """追加する用語集の選択で name を選び、使う用語集の追加ボタンを押す。"""
    combo = _combo(panel, "glossary_preset_glossary_select")
    combo.setCurrentIndex(combo.findText(name))
    _button(panel, "glossary_preset_glossary_add").click()


# === set_glossaries ===


def test_glossary_panel_set_glossaries(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """一覧と行の数・使うプリセットを出し、補正に使うプリセットの消すボタンを無効の扱いにする（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（5 行（オン 3）の「yogo」と 2 行の「会議用」、「既定」「会議」の 2 件のプリセットと、補正に使う「会議」）
    first, second = _two_glossaries(tmp_path)
    first_rows = [
        GlossaryEntry(wrong=f"誤{number}", right=f"正{number}", enabled=number < 3)
        for number in range(5)
    ]
    second_rows = [GlossaryEntry(wrong="い", right="B"), GlossaryEntry(wrong="う", right="C")]

    # 実行
    opened = open_panel(
        [first, second],
        {first.path: first_rows, second.path: second_rows},
        presets=_two_presets(),
        active_preset="会議",
    )

    # 検証
    assert _label(opened.panel, "glossary_count_0").text() == "5 行（オン 3）"
    assert _label(opened.panel, "glossary_count_1").text() == "2 行（オン 2）"
    assert _label(opened.panel, "glossary_presets_using_0").text() == "既定・会議"
    assert _label(opened.panel, "glossary_preset_count_0").text() == "1 件"
    assert _label(opened.panel, "glossary_preset_count_1").text() == "2 件"
    assert _button(opened.panel, "glossary_preset_active_0").isChecked() is False
    assert _button(opened.panel, "glossary_preset_active_1").isChecked() is True
    assert _used_glossary_names(opened.panel) == ["会議用", "yogo"]
    assert _label(opened.panel, "glossary_detail_title").text() == "用語集「会議用」の行"
    assert (
        _label(opened.panel, "glossary_list_note").text()
        == "消した用語集は、使っているプリセットからも外れる。"
    )
    _button(opened.panel, "glossary_preset_remove_1").click()
    assert len(opened.panel.collect_presets()) == 2


def test_glossary_panel_set_glossaries_when_unreadable(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """読めない用語集も一覧に出し、行の表の代わりに理由を出す（正常系）。"""
    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集のうち、2 件目で行を読む関数が GlossaryReadError を送出する。プリセットは 1 件目だけを使う「既定」）
    first, second = _two_glossaries(tmp_path)

    # 実行
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: GlossaryReadError(UNREADABLE_REASON),
        },
    )
    _button(opened.panel, "glossary_pick_1").click()

    # 検証
    assert len(opened.panel.collect()) == 2
    assert _label(opened.panel, "glossary_count_1").text() == "読めません"
    assert _label(opened.panel, "glossary_unreadable").text() == (
        f"この用語集の CSV を読めませんでした（{UNREADABLE_REASON}）。"
        "保存しても、この CSV は書き換えません。"
    )
    assert _visible_edits(opened.panel, "glossary_entry_wrong_") == []
    assert _button(opened.panel, "add_glossary_entry_button").isEnabled() is False
    assert _combo_texts(_combo(opened.panel, "glossary_preset_glossary_select")) == ["会議用"]


def test_glossary_panel_set_glossaries_when_preset_empty(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集が無いプリセットでは、表の代わりに文を出し、一覧の 1 件目の行の表を出す（正常系）。"""
    from voice_paste.shared.settings import GlossaryPresetSettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集と、glossaries が [] の「空」の 1 件のプリセット）
    first, second = _two_glossaries(tmp_path)

    # 実行
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=[GlossaryPresetSettings(name="空", glossaries=[])],
    )

    # 検証
    assert _label(opened.panel, "glossary_preset_glossaries_empty").isVisible() is True
    assert _label(opened.panel, "glossary_detail_title").text() == "用語集「yogo」の行"
    assert _combo_texts(_combo(opened.panel, "glossary_preset_glossary_select")) == [
        "yogo",
        "会議用",
    ]


def test_glossary_panel_set_glossaries_when_single_glossary(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集が 1 件だけのときは、その消すボタンを無効の扱いにする（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件の用語集と、それを使う「既定」の 1 件のプリセットで開く）
    first = _two_glossaries(tmp_path)[0]
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})

    # 実行（用語集の消すボタンを押す。用語集を 1 つ足してからもう一度押す）
    _button(opened.panel, "glossary_remove_0").click()
    after_first_click = len(opened.panel.collect())
    tooltip = _button(opened.panel, "glossary_remove_0").toolTip()
    opened.panel.add_glossary()
    _button(opened.panel, "glossary_remove_0").click()
    after_second_click = len(opened.panel.collect())
    _button(opened.panel, "glossary_remove_0").click()

    # 検証（1 回目は減らず、2 回目は 1 件に減って「既定」の使う用語集からも外れ、残った 1 件は押しても減らない）
    assert after_first_click == 1
    assert tooltip == "最後の用語集は消せません"
    assert after_second_click == 1
    assert len(opened.panel.collect()) == 1
    assert opened.panel.collect_presets() == [{"name": "既定", "glossaries": []}]


# === collect ===


def test_glossary_panel_collect(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """名前を変えた用語集と足した用語集を並びの順に返す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件の用語集の名前を変え、用語集を 1 つ足して名前を入れる）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    _visible_edits(opened.panel, "glossary_name_")[0].setText("新しい名前")
    opened.panel.add_glossary()
    _visible_edits(opened.panel, "glossary_name_")[0].setText("会議用")

    # 実行
    collected = opened.panel.collect()

    # 検証（1 件目は変えた名前と元の場所、2 件目は入れた名前と決めた場所）
    assert [item["name"] for item in collected] == ["新しい名前", "会議用"]
    assert [Path(item["path"]) for item in collected] == [first.path, opened.new_path]


# === collect_presets ===


def test_glossary_panel_collect_presets(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """並べ替えた順と、名前を変えた用語集の今の名前で返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（「会議」の使う用語集の 1 行目で Alt+↓ を押し、「yogo」の名前を「共通」に変える）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=_two_presets(),
    )
    _button(opened.panel, "glossary_preset_pick_1").click()
    QTest.keyClick(
        _button(opened.panel, "glossary_preset_glossary_remove_0"),
        Qt.Key.Key_Down,
        Qt.KeyboardModifier.AltModifier,
    )
    _button(opened.panel, "glossary_pick_0").click()
    _visible_edits(opened.panel, "glossary_name_")[0].setText("共通")

    # 実行
    presets = opened.panel.collect_presets()

    # 検証
    assert presets == [
        {"name": "既定", "glossaries": ["共通"]},
        {"name": "会議", "glossaries": ["共通", "会議用"]},
    ]


def test_glossary_panel_collect_presets_when_glossary_removed(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集を消すと、全てのプリセットから外れる（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（用語集の一覧から「yogo」を消す）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=_two_presets(),
    )
    _button(opened.panel, "glossary_remove_0").click()

    # 実行
    presets = opened.panel.collect_presets()

    # 検証
    assert presets == [
        {"name": "既定", "glossaries": []},
        {"name": "会議", "glossaries": ["会議用"]},
    ]


def test_glossary_panel_collect_presets_when_added(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """足したプリセットに用語集を追加すると末尾に返し、追加した用語集は選択肢から消える（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件のプリセットでプリセットを足し、名前を「議事録」にして「会議用」を追加する）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
    )
    opened.panel.add_glossary_preset()
    _visible_edits(opened.panel, "glossary_preset_name_")[0].setText("議事録")
    _add_preset_glossary(opened.panel, "会議用")

    # 実行
    presets = opened.panel.collect_presets()

    # 検証
    assert presets == [
        {"name": "既定", "glossaries": ["yogo"]},
        {"name": "議事録", "glossaries": ["会議用"]},
    ]
    assert _combo_texts(_combo(opened.panel, "glossary_preset_glossary_select")) == ["yogo"]


# === active_preset_name ===


def test_glossary_panel_active_preset_name(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """補正に使うプリセットを切り替えてから名前を変えると、変えた名前を返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件目のプリセットを補正に使うプリセットにし、その名前を変える）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=_two_presets(),
    )
    _button(opened.panel, "glossary_preset_active_1").click()
    _button(opened.panel, "glossary_preset_pick_1").click()
    _visible_edits(opened.panel, "glossary_preset_name_")[0].setText("改名")

    # 実行
    name = opened.panel.active_preset_name()

    # 検証（1 件目のプリセットの消すボタンが押せるようになり、押すと一覧から消える）
    assert name == "改名"
    _button(opened.panel, "glossary_preset_remove_0").click()
    assert len(opened.panel.collect_presets()) == 1


# === changed_rows ===


def test_glossary_panel_changed_rows(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """行を変えた用語集だけを返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集のうち、2 件目の行を 1 つオフにする）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [
                GlossaryEntry(wrong="い", right="B"),
                GlossaryEntry(wrong="う", right="C"),
            ],
        },
    )
    _button(opened.panel, "glossary_pick_1").click()
    _visible_buttons(opened.panel, "glossary_entry_on_")[0].click()

    # 実行
    changed = opened.panel.changed_rows()

    # 検証（2 件目の場所だけを持ち、その行の enabled が False）
    assert changed == {
        second.path: [
            GlossaryEntry(wrong="い", right="B", enabled=False),
            GlossaryEntry(wrong="う", right="C"),
        ]
    }


def test_glossary_panel_changed_rows_when_untouched(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """行を変えていなければ空（名前だけ変えても空）（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件目の名前だけを変える）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    _visible_edits(opened.panel, "glossary_name_")[0].setText("改名")

    # 実行
    changed = opened.panel.changed_rows()

    # 検証
    assert changed == {}


def test_glossary_panel_changed_rows_when_added(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """足した用語集は行が無くても返し、両方が空の行は除く（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（用語集を 1 つ足し、行を 2 つ足して 1 つだけに値を入れる）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    opened.panel.add_glossary()
    add_entry = _button(opened.panel, "add_glossary_entry_button")
    add_entry.click()
    add_entry.click()
    _visible_edits(opened.panel, "glossary_entry_wrong_")[0].setText("う")
    _visible_edits(opened.panel, "glossary_entry_right_")[0].setText("U")

    # 実行
    changed = opened.panel.changed_rows()

    # 検証（足した用語集の場所を持ち、行は値を入れた 1 つだけ）
    assert changed == {opened.new_path: [GlossaryEntry(wrong="う", right="U")]}


def test_glossary_panel_changed_rows_when_unreadable(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """読めなかった用語集は書き戻しに入れない（正常系）。"""
    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings

    # 準備（読めなかった用語集の名前を変え、プリセットの使う用語集に追加する）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel(
        [first],
        {first.path: GlossaryReadError(UNREADABLE_REASON)},
        presets=[GlossaryPresetSettings(name="既定", glossaries=[])],
    )
    _visible_edits(opened.panel, "glossary_name_")[0].setText("改名")
    _add_preset_glossary(opened.panel, "改名")

    # 実行
    changed = opened.panel.changed_rows()

    # 検証
    assert changed == {}


# === change_values ===


def test_glossary_panel_change_values(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集ごとの名前と行、プリセットごとの名前と使う用語集、補正に使うプリセットの識別を返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集と 2 件のプリセットを持ち 2 件目のプリセットを補正に使う一覧で開き、1 件目の用語集に両方が空の行を 1 つ足す）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B", enabled=False)],
        },
        presets=_two_presets(),
        active_preset="会議",
    )
    _button(opened.panel, "glossary_pick_0").click()
    _button(opened.panel, "add_glossary_entry_button").click()

    # 実行
    values = opened.panel.change_values()

    # 検証（1 件目の用語集の行に足した空の行は入らない）
    assert set(values) == {
        f"glossaries[{first.path}]",
        f"glossaries[{second.path}]",
        "glossary_presets[0]",
        "glossary_presets[1]",
        "active_glossary_preset",
    }
    assert values[f"glossaries[{first.path}]"] == ("yogo", [GlossaryEntry(wrong="あ", right="A")])
    assert values[f"glossaries[{second.path}]"] == (
        "会議用",
        [GlossaryEntry(wrong="い", right="B", enabled=False)],
    )
    assert values["glossary_presets[0]"] == ("既定", [first.path])
    assert values["glossary_presets[1]"] == ("会議", [second.path, first.path])
    assert str(values["active_glossary_preset"]) == "1"


def test_glossary_panel_change_values_when_active_renamed(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """補正に使うプリセットの名前を変えても、補正に使うプリセットの値は変わらない（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件目のプリセットを補正に使う一覧で開き、変える前の値を取る）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=_two_presets(),
        active_preset="会議",
    )
    before = opened.panel.change_values()

    # 実行（2 件目のプリセットの名前を、前後に空白を付けた「改名」に変える）
    _button(opened.panel, "glossary_preset_pick_1").click()
    _visible_edits(opened.panel, "glossary_preset_name_")[0].setText("  改名  ")
    after = opened.panel.change_values()

    # 検証（2 件目のプリセットのキーの名前だけが、前後の空白を除いた新しい名前になる）
    assert after["glossary_presets[1]"] == ("改名", [second.path, first.path])
    assert after["glossary_presets[0]"] == before["glossary_presets[0]"]
    assert after["active_glossary_preset"] == before["active_glossary_preset"]


def test_glossary_panel_change_values_when_glossary_renamed(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集の名前を変えても、プリセットの値は変わらない（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（プリセットが使う用語集の名前を変える前の値を取る）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        presets=_two_presets(),
    )
    before = opened.panel.change_values()

    # 実行（1 件目の用語集の名前を変える）
    _button(opened.panel, "glossary_pick_0").click()
    _visible_edits(opened.panel, "glossary_name_")[0].setText("共通")
    after = opened.panel.change_values()

    # 検証（その用語集のキーの名前だけが変わり、プリセットのキーの値は開いたときと同じ）
    assert after[f"glossaries[{first.path}]"] == ("共通", [GlossaryEntry(wrong="あ", right="A")])
    assert after["glossary_presets[0]"] == before["glossary_presets[0]"]
    assert after["glossary_presets[1]"] == before["glossary_presets[1]"]


def test_glossary_panel_change_values_when_added(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """足した用語集とプリセットは新しいキーで返す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件の用語集と 1 件のプリセットの一覧で開く）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})

    # 実行
    opened.panel.add_glossary()
    opened.panel.add_glossary_preset()
    values = opened.panel.change_values()

    # 検証（足した用語集とプリセットのキーが名前も行も使う用語集も空で、キーは 5 つ）
    assert values[f"glossaries[{opened.new_path}]"] == ("", [])
    assert values["glossary_presets[1]"] == ("", [])
    assert set(values) == {
        f"glossaries[{first.path}]",
        f"glossaries[{opened.new_path}]",
        "glossary_presets[0]",
        "glossary_presets[1]",
        "active_glossary_preset",
    }


def test_glossary_panel_change_values_when_unreadable(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """読めなかった用語集の行は None で返す（正常系）。"""
    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件のうち 2 件目で行を読む関数が GlossaryReadError を送出する一覧で開く）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: GlossaryReadError(UNREADABLE_REASON),
        },
    )

    # 実行
    values = opened.panel.change_values()

    # 検証（読めなかった用語集は名前と None。読めた用語集は行を持つ）
    assert values[f"glossaries[{second.path}]"] == ("会議用", None)
    assert values[f"glossaries[{first.path}]"] == ("yogo", [GlossaryEntry(wrong="あ", right="A")])


# === mark_saved ===


def test_glossary_panel_mark_saved(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """保存した行を基準にし、そこから戻した用語集を書き戻しに入れる（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件目の行を 1 つオフにしてから mark_saved を呼ぶ）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [
                GlossaryEntry(wrong="あ", right="A"),
                GlossaryEntry(wrong="い", right="B"),
            ],
            second.path: [GlossaryEntry(wrong="う", right="C")],
        },
    )
    _visible_buttons(opened.panel, "glossary_entry_on_")[0].click()

    # 実行
    opened.panel.mark_saved()
    after_mark_saved = opened.panel.changed_rows()
    _visible_buttons(opened.panel, "glossary_entry_on_")[0].click()
    after_revert = opened.panel.changed_rows()

    # 検証（mark_saved の直後は空、オンに戻すと 1 件目の場所を持ち、その行がオン）
    assert after_mark_saved == {}
    assert after_revert == {
        first.path: [
            GlossaryEntry(wrong="あ", right="A"),
            GlossaryEntry(wrong="い", right="B"),
        ]
    }


def test_glossary_panel_mark_saved_when_added(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """足した用語集も保存した行が基準になる（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（用語集を 1 つ足し、行を 1 つ入れる）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    opened.panel.add_glossary()
    _button(opened.panel, "add_glossary_entry_button").click()
    _visible_edits(opened.panel, "glossary_entry_wrong_")[0].setText("う")
    _visible_edits(opened.panel, "glossary_entry_right_")[0].setText("U")

    # 実行
    opened.panel.mark_saved()

    # 検証
    assert opened.panel.changed_rows() == {}


# === add_glossary ===


def test_glossary_panel_add_glossary(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """空の用語集を末尾に足し、行が無いときの文を出す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件の用語集の一覧）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    changed_count: list[int] = []
    opened.panel.changed.connect(lambda: changed_count.append(1))

    # 実行
    opened.panel.add_glossary()

    # 検証（どのプリセットの使う用語集にも入らず、追加する用語集の選択に出る）
    assert len(opened.panel.collect()) == 2
    assert _button(opened.panel, "glossary_pick_1").text() == "（名前未入力）"
    assert _label(opened.panel, "glossary_count_1").text() == "0 行（オン 0）"
    assert _label(opened.panel, "glossary_entries_empty").isVisible() is True
    assert opened.panel.collect_presets() == [{"name": "既定", "glossaries": ["yogo"]}]
    assert _combo(opened.panel, "glossary_preset_glossary_select").count() == 1
    assert set(opened.new_glossary_path.call_args.args[0]) == {first.path}
    assert changed_count == [1]


# === add_glossary_preset ===


def test_glossary_panel_add_glossary_preset(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """空のプリセットを末尾に足し、使う用語集が無いときの文を出す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件のプリセットの一覧）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})
    changed_count: list[int] = []
    opened.panel.changed.connect(lambda: changed_count.append(1))

    # 実行
    opened.panel.add_glossary_preset()

    # 検証
    assert len(opened.panel.collect_presets()) == 2
    assert _button(opened.panel, "glossary_preset_pick_1").text() == "名前未入力のプリセット"
    assert _label(opened.panel, "glossary_preset_count_1").text() == "0 件"
    assert _label(opened.panel, "glossary_preset_glossaries_empty").isVisible() is True
    assert opened.panel.focusWidget() is _visible_edits(opened.panel, "glossary_preset_name_")[0]
    assert _button(opened.panel, "glossary_preset_active_0").isChecked() is True
    assert changed_count == [1]


# === find_glossary_row_errors ===


def test_find_glossary_row_errors() -> None:
    """誤変換だけが空の行を返し、正しい表記だけが空の行は返さない（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry
    from voice_paste.ui.windows.settings_glossaries import find_glossary_row_errors

    # 準備（「あ,い」「,う」「え,」「,」の 4 行。2 行目はオフ）
    entries = [
        GlossaryEntry(wrong="あ", right="い"),
        GlossaryEntry(wrong="", right="う", enabled=False),
        GlossaryEntry(wrong="え", right=""),
        GlossaryEntry(wrong="", right=""),
    ]

    # 実行
    errors = find_glossary_row_errors(entries)

    # 検証
    assert errors == [(1, "wrong")]


def test_find_glossary_row_errors_when_valid() -> None:
    """両方がある行と両方が空の行だけなら空（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry
    from voice_paste.ui.windows.settings_glossaries import find_glossary_row_errors

    # 準備（「あ,い」「,」の 2 行）
    entries = [GlossaryEntry(wrong="あ", right="い"), GlossaryEntry(wrong="", right="")]

    # 実行
    errors = find_glossary_row_errors(entries)

    # 検証
    assert errors == []
