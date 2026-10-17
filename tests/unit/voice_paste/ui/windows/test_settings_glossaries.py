"""ui/windows/settings_glossaries.py（GlossaryPanel の set_glossaries・collect・active_name・changed_rows・change_values・mark_saved・add_glossary、find_glossary_row_errors）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
行を読む関数と足す用語集の場所を決める関数は Mock に差し替える。
部品は画面設計の項目 ID（glossary_pick_{n}・glossary_active_{n}・glossary_count_{n}・glossary_remove_{n} など）の objectName で引く。
行の表に出ている欄は、objectName の前方一致で、画面に出ているものを名前の順で引く。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.settings import GlossarySettings
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
        active_name: str | None = None,
    ) -> Opened:
        """場所の行を返す（GlossaryReadError を渡した場所は送出する）関数で部品を作り、一覧を入れる。"""

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
        panel.set_glossaries(glossaries, active_name or glossaries[0].name)
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


# === set_glossaries ===


def test_glossary_panel_set_glossaries(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """一覧と行の数を出し、補正に使う用語集の消すボタンを無効の扱いにする（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（5 行（オン 3）と 2 行の 2 件の用語集と、1 件目の名前）
    first, second = _two_glossaries(tmp_path)
    first_rows = [
        GlossaryEntry(wrong=f"誤{number}", right=f"正{number}", enabled=number < 3)
        for number in range(5)
    ]
    second_rows = [GlossaryEntry(wrong="い", right="B"), GlossaryEntry(wrong="う", right="C")]

    # 実行
    opened = open_panel(
        [first, second], {first.path: first_rows, second.path: second_rows}, active_name="yogo"
    )

    # 検証
    assert _label(opened.panel, "glossary_count_0").text() == "5 行（オン 3）"
    assert _label(opened.panel, "glossary_count_1").text() == "2 行（オン 2）"
    assert _button(opened.panel, "glossary_active_0").isChecked() is True
    assert _button(opened.panel, "glossary_active_1").isChecked() is False
    _button(opened.panel, "glossary_remove_0").click()
    assert len(opened.panel.collect()) == 2


def test_glossary_panel_set_glossaries_when_unreadable(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """読めない用語集も一覧に出し、行の表の代わりに理由を出す（正常系）。"""
    from voice_paste.shared.errors import GlossaryReadError
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集のうち、2 件目で行を読む関数が GlossaryReadError を送出する）
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


# === active_name ===


def test_glossary_panel_active_name(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """補正に使う用語集を切り替えてから名前を変えると、変えた名前を返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件目を補正に使う用語集にし、その名前を変える）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
    )
    _button(opened.panel, "glossary_active_1").click()
    _button(opened.panel, "glossary_pick_1").click()
    _visible_edits(opened.panel, "glossary_name_")[0].setText("改名")

    # 実行
    name = opened.panel.active_name()

    # 検証（1 件目の消すボタンが押せるようになり、押すと一覧から消える）
    assert name == "改名"
    _button(opened.panel, "glossary_remove_0").click()
    assert len(opened.panel.collect()) == 1


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
    from voice_paste.shared.settings import GlossarySettings

    # 準備（読めなかった用語集の名前を変え、補正に使う用語集に選ぶ）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: GlossaryReadError(UNREADABLE_REASON)})
    _visible_edits(opened.panel, "glossary_name_")[0].setText("改名")

    # 実行
    changed = opened.panel.changed_rows()

    # 検証
    assert changed == {}


# === change_values ===


def test_glossary_panel_change_values(open_panel: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集ごとの名前と行と、補正に使う用語集の場所を返す（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集を持ち 2 件目を補正に使う一覧で開き、1 件目に両方が空の行を 1 つ足す）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B", enabled=False)],
        },
        active_name="会議用",
    )
    _button(opened.panel, "glossary_pick_0").click()
    _button(opened.panel, "add_glossary_entry_button").click()

    # 実行
    values = opened.panel.change_values()

    # 検証（キーは 2 件の場所と active_glossary。1 件目の行に足した空の行は入らない）
    assert set(values) == {
        f"glossaries[{first.path}]",
        f"glossaries[{second.path}]",
        "active_glossary",
    }
    assert values[f"glossaries[{first.path}]"] == ("yogo", [GlossaryEntry(wrong="あ", right="A")])
    assert values[f"glossaries[{second.path}]"] == (
        "会議用",
        [GlossaryEntry(wrong="い", right="B", enabled=False)],
    )
    assert Path(str(values["active_glossary"])) == second.path


def test_glossary_panel_change_values_when_active_renamed(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """補正に使う用語集の名前を変えても、補正に使う用語集の値は変わらない（正常系）。"""
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件目を補正に使う一覧で開き、変える前の値を取る）
    first, second = _two_glossaries(tmp_path)
    opened = open_panel(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        active_name="会議用",
    )
    before = opened.panel.change_values()

    # 実行（2 件目の名前を、前後に空白を付けた「改名」に変える）
    _button(opened.panel, "glossary_pick_1").click()
    _visible_edits(opened.panel, "glossary_name_")[0].setText("  改名  ")
    after = opened.panel.change_values()

    # 検証（2 件目のキーの名前だけが、前後の空白を除いた新しい名前になる）
    assert after[f"glossaries[{second.path}]"] == ("改名", [GlossaryEntry(wrong="い", right="B")])
    assert after[f"glossaries[{first.path}]"] == before[f"glossaries[{first.path}]"]
    assert after["active_glossary"] == before["active_glossary"]


def test_glossary_panel_change_values_when_added(
    open_panel: Callable[..., Opened], tmp_path: Path
) -> None:
    """足した用語集は新しいキーで返す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件の用語集の一覧で開く）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_panel([first], {first.path: [GlossaryEntry(wrong="あ", right="A")]})

    # 実行
    opened.panel.add_glossary()
    values = opened.panel.change_values()

    # 検証（足した用語集の場所のキーが名前も行も空で、キーは 3 つ）
    assert values[f"glossaries[{opened.new_path}]"] == ("", [])
    assert set(values) == {
        f"glossaries[{first.path}]",
        f"glossaries[{opened.new_path}]",
        "active_glossary",
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

    # 検証
    assert len(opened.panel.collect()) == 2
    assert _button(opened.panel, "glossary_pick_1").text() == "（名前未入力）"
    assert _label(opened.panel, "glossary_count_1").text() == "0 行（オン 0）"
    assert _label(opened.panel, "glossary_entries_empty").isVisible() is True
    assert opened.panel.active_name() == "yogo"
    assert set(opened.new_glossary_path.call_args.args[0]) == {first.path}
    assert changed_count == [1]


# === find_glossary_row_errors ===


def test_find_glossary_row_errors() -> None:
    """片方だけが空の行を、空の側の項目つきで返す（正常系）。"""
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
    assert errors == [(1, "wrong"), (2, "right")]


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
