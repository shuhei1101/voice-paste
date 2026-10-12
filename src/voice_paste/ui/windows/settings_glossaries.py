"""設定画面の「用語集」のまとまりに置く、用語集の一覧と、選んだ用語集の名前の欄・行の表。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.errors import GlossaryReadError
from voice_paste.shared.settings import GlossarySettings
from voice_paste.shared.types import GlossaryEntry
from voice_paste.ui.windows.settings_fields import set_invalid

logger = logging.getLogger(__name__)

type RowField = Literal["wrong", "right"]
"""行の表の欄の種類（誤変換・正しい表記）。"""

type GlossaryField = Literal["name", "wrong", "right"]
"""エラーを出す・フォーカスを移す欄の種類（用語集の名前・行の誤変換・行の正しい表記）。"""

UNNAMED_TEXT: str = "（名前未入力）"
"""名前が空の用語集を、一覧と行の見出しに出す表示。"""

UNREADABLE_COUNT_TEXT: str = "読めません"
"""CSV を読めなかった用語集の、行の数の表示。"""

NAME_DISPLAY_MAX_CHARS: int = 20
"""一覧の名前のボタンに出す名前の長さの上限（超えたら末尾を省く）。"""

ACTIVE_REMOVE_TOOLTIP: str = "補正に使う用語集は消せません"
"""補正に使う用語集の消すボタンに出すツールチップ。"""

DIMMED_OPACITY: float = 0.4
"""押せない扱いの消すボタンと、オフの行の欄を薄くする濃さ。"""

NAME_PLACEHOLDER: str = "例: 会議用"
"""名前の欄のプレースホルダ。"""

EMPTY_ROWS_TEXT: str = "この用語集にはまだ行がありません。"
"""行が 1 つも無い用語集の、行の表の代わりに出す文。"""

LEGEND_TEXT: str = "上の行から順に置き換える。オフの行は補正に使わない。"
"""行の順とオン・オフが補正にどう効くかを示す凡例。"""

ROW_ERROR_MESSAGES: dict[str, str] = {
    "wrong": "誤変換を入れてください。",
    "right": "正しい表記を入れてください。",
}
"""片方だけが空の行の、空の側の欄の下に出すエラーの文言。"""


@dataclass(eq=False)
class _RowState:
    """行の表の 1 行の、今の入力。"""

    wrong: str
    right: str
    enabled: bool


@dataclass(eq=False)
class _GlossaryState:
    """一覧の用語集 1 つの、今の入力。"""

    name: str
    path: Path
    rows: list[_RowState]
    original: list[GlossaryEntry] | None
    """開いたときに読んだ行。足した用語集と、読めなかった用語集は None。"""
    unreadable: str | None = None
    """CSV を読めなかった理由。読めたら None。"""


@dataclass
class _ListRow:
    """一覧の 1 行の部品。"""

    radio: QRadioButton
    pick_button: QPushButton
    count_label: QLabel
    remove_button: QPushButton


def find_glossary_row_errors(entries: Sequence[GlossaryEntry]) -> list[tuple[int, RowField]]:
    """用語集の行のうち、誤変換か正しい表記の片方だけが空の行と、空の側の項目を返す。オフの行も確かめる。"""
    errors: list[tuple[int, RowField]] = []
    for position, entry in enumerate(entries):
        # 誤変換だけが空: 誤変換の欄、正しい表記だけが空: 正しい表記の欄（両方が空の行は返さない）
        if not entry.wrong and entry.right:
            errors.append((position, "wrong"))
        elif entry.wrong and not entry.right:
            errors.append((position, "right"))
    return errors


def _display_name(name: str) -> str:
    """名前の表示（前後の空白を除き、空なら「（名前未入力）」）を返す。"""
    return name.strip() or UNNAMED_TEXT


def _spoken_name(name: str) -> str:
    """読み上げの名前に使う用語集の呼び方（名前が空なら「名前未入力の用語集」）を返す。"""
    return name.strip() or "名前未入力の用語集"


def _clear_layout(layout: QLayout) -> None:
    """レイアウトの部品を全て外して捨てる。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def _dim(widget: QWidget, *, dimmed: bool) -> None:
    """部品を薄くする・戻す。"""
    if dimmed:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(DIMMED_OPACITY)
        widget.setGraphicsEffect(effect)
    else:
        widget.setGraphicsEffect(None)


class GlossaryPanel(QWidget):
    """設定画面の「用語集」のまとまりに置く、用語集の一覧と、選んだ用語集の名前の欄・行の表。

    足す・消す・入力はこの部品の中だけを変え、settings.toml と CSV へは設定画面の保存で書く。
    """

    changed = Signal()
    """用語集と行を足す・消す、補正に使う用語集の切り替え、欄の入力、行のオン・オフで値が変わった。"""

    def __init__(
        self,
        read_glossary: Callable[[Path], list[GlossaryEntry]],
        new_glossary_path: Callable[[Collection[Path]], Path],
        parent: QWidget | None = None,
    ) -> None:
        """行を読む関数と、足す用語集の場所を決める関数を受けて、空の部品を作る。"""
        super().__init__(parent)
        self._read_glossary = read_glossary
        self._new_glossary_path = new_glossary_path
        self._glossaries: list[_GlossaryState] = []
        self._shown = 0
        """行の表を出している用語集の添字。"""
        self._active = 0
        """補正に使う用語集の添字。"""
        self._list_rows: list[_ListRow] = []
        self._active_group = QButtonGroup(self)
        self._errors: dict[tuple[int, GlossaryField, int | None], list[str]] = {}
        """出すエラー（用語集の何件目か・項目・何行目か → 文言）。行の表を切り替えても残す。"""
        self._inputs: dict[tuple[GlossaryField, int | None], QLineEdit] = {}
        self._error_labels: dict[tuple[GlossaryField, int | None], QLabel] = {}
        self.setObjectName("glossary_panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        list_heading = QLabel("用語集の一覧")
        list_heading.setProperty("role", "heading")
        outer.addWidget(list_heading)
        list_frame = QFrame()
        list_frame.setObjectName("glossary_list")
        list_frame.setAccessibleName("用語集の一覧（補正に使う用語集を 1 つ選ぶ）")
        self._list_layout = QVBoxLayout(list_frame)
        outer.addWidget(list_frame)
        add_button = QPushButton("用語集を足す")
        add_button.setObjectName("add_glossary_button")
        add_button.clicked.connect(self.add_glossary)
        outer.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        detail_frame = QFrame()
        detail_frame.setProperty("role", "surface")
        self._detail_layout = QVBoxLayout(detail_frame)
        outer.addWidget(detail_frame)

    # --- 値の出し入れ ---

    def set_glossaries(self, glossaries: Sequence[GlossarySettings], active_name: str) -> None:
        """渡した用語集で一覧を作り直し、用語集ごとに行を読んで開いたときの行として控え、補正に使う用語集の行の表を出す。"""
        self._glossaries = []
        for glossary in glossaries:
            try:
                rows = self._read_glossary(glossary.path)
            except GlossaryReadError as error:
                # 読めない用語集も一覧に残し、理由を控える
                logger.warning(f"用語集を読めなかった（{glossary.path}: {error}）")
                self._glossaries.append(
                    _GlossaryState(glossary.name, glossary.path, [], None, str(error))
                )
                continue
            self._glossaries.append(
                _GlossaryState(
                    glossary.name,
                    glossary.path,
                    [_RowState(row.wrong, row.right, row.enabled) for row in rows],
                    list(rows),
                )
            )
        names = [glossary.name for glossary in glossaries]
        self._active = names.index(active_name) if active_name in names else 0
        self._shown = self._active
        self._errors.clear()
        self._rebuild_list()
        self._rebuild_detail()

    def collect(self) -> list[dict[str, Any]]:
        """今の並びの用語集を、settings.toml と同じ形の dict（name・path）の並びにする。name は前後の空白を除く。"""
        return [
            {"name": glossary.name.strip(), "path": glossary.path} for glossary in self._glossaries
        ]

    def active_name(self) -> str:
        """補正に使う用語集に選んでいる用語集の、今の名前の欄の値（前後の空白を除く）を返す。"""
        return self._glossaries[self._active].name.strip()

    def changed_rows(self) -> dict[Path, list[GlossaryEntry]]:
        """行を変えた用語集と足した用語集だけの、CSV の場所 → 行（表の順。両方が空の行は除く）を返す。"""
        changed: dict[Path, list[GlossaryEntry]] = {}
        for glossary in self._glossaries:
            # 読めなかった用語集は、保存してもその CSV に触れない
            if glossary.unreadable is not None:
                continue
            entries = [entry for entry in self._entries(glossary) if entry.wrong or entry.right]
            # 足した用語集か、開いたときと行が違う用語集だけを書き戻す（名前だけ変えた用語集は入らない）
            if glossary.original is None or entries != glossary.original:
                changed[glossary.path] = entries
        return changed

    def row_errors(self) -> list[tuple[int, int, RowField]]:
        """読めた全ての用語集の行を確かめ、片方だけが空の行の（用語集の何件目か, 何行目か, 空の側の項目）を返す。"""
        errors: list[tuple[int, int, RowField]] = []
        for position, glossary in enumerate(self._glossaries):
            if glossary.unreadable is not None:
                continue
            errors.extend(
                (position, row, field)
                for row, field in find_glossary_row_errors(self._entries(glossary))
            )
        return errors

    @staticmethod
    def _entries(glossary: _GlossaryState) -> list[GlossaryEntry]:
        """用語集の今の行を、前後の空白を除いた GlossaryEntry の並びにする。"""
        return [
            GlossaryEntry(wrong=row.wrong.strip(), right=row.right.strip(), enabled=row.enabled)
            for row in glossary.rows
        ]

    # --- 操作 ---

    def add_glossary(self) -> None:
        """末尾に名前が空で行の無い用語集を足し、その行の表を出して名前の欄へフォーカスを移し、changed を emit する。"""
        path = self._new_glossary_path([glossary.path for glossary in self._glossaries])
        self._glossaries.append(_GlossaryState("", path, [], None))
        self._shown = len(self._glossaries) - 1
        self._rebuild_list()
        self._rebuild_detail()
        self._inputs[("name", None)].setFocus()
        self.changed.emit()

    def focus_field(self, position: int, field: GlossaryField, row: int | None = None) -> None:
        """用語集の何件目かと項目（と行）で欄を探し、その用語集の行の表を出してフォーカスを移す。"""
        self._show(position)
        edit = self._inputs.get((field, row))
        if edit is not None:
            edit.setFocus()

    def show_error(
        self, position: int, field: GlossaryField, message: str, row: int | None = None
    ) -> None:
        """用語集の何件目かと項目（と行）の欄の下にエラーを出し、欄をエラーの見た目にする。"""
        self._errors.setdefault((position, field, row), []).append(message)
        if position == self._shown:
            self._apply_error(field, row, self._errors[(position, field, row)])

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て消す。"""
        self._errors.clear()
        for key, label in self._error_labels.items():
            label.clear()
            label.hide()
            set_invalid(self._inputs[key], invalid=False)

    def _apply_error(self, field: GlossaryField, row: int | None, messages: list[str]) -> None:
        """今出している行の表の欄の下にエラーを出し、欄を赤くする。"""
        label = self._error_labels.get((field, row))
        edit = self._inputs.get((field, row))
        if label is None or edit is None:
            return
        label.setText("\n".join(messages))
        label.show()
        set_invalid(edit, invalid=True)

    # --- 一覧 ---

    def _rebuild_list(self) -> None:
        """用語集の一覧（補正に使う用語集の選択・名前のボタン・行の数・消すボタン）を作り直す。"""
        for list_row in self._list_rows:
            self._active_group.removeButton(list_row.radio)
        _clear_layout(self._list_layout)
        self._list_rows = []
        for index in range(len(self._glossaries)):
            # 行の表を出している用語集の行は、背景を変えて示す
            frame = QFrame()
            if index == self._shown:
                frame.setProperty("role", "surface")
            line = QHBoxLayout(frame)
            line.setContentsMargins(4, 2, 4, 2)

            radio = QRadioButton()
            radio.setObjectName(f"glossary_active_{index}")
            radio.setChecked(index == self._active)
            radio.toggled.connect(lambda checked, position=index: self._on_active(position, checked))
            self._active_group.addButton(radio)
            pick_button = QPushButton()
            pick_button.setObjectName(f"glossary_pick_{index}")
            pick_button.setFlat(True)
            pick_button.clicked.connect(lambda _checked=False, position=index: self._show(position))
            count_label = QLabel()
            count_label.setObjectName(f"glossary_count_{index}")
            remove_button = QPushButton("×")
            remove_button.setObjectName(f"glossary_remove_{index}")
            remove_button.clicked.connect(
                lambda _checked=False, position=index: self._remove_glossary(position)
            )
            line.addWidget(radio)
            line.addWidget(pick_button, 1)
            line.addWidget(count_label)
            line.addWidget(remove_button)
            self._list_layout.addWidget(frame)
            frame.show()
            self._list_rows.append(_ListRow(radio, pick_button, count_label, remove_button))
            self._sync_list_row(index)

    def _sync_list_row(self, index: int) -> None:
        """一覧の 1 行の表示（名前・行の数・読み上げの名前・消すボタンの扱い）を、今の入力に合わせる。"""
        glossary = self._glossaries[index]
        row = self._list_rows[index]
        shown_name = _display_name(glossary.name)
        spoken = _spoken_name(glossary.name)
        clipped = (
            shown_name
            if len(shown_name) <= NAME_DISPLAY_MAX_CHARS
            else shown_name[: NAME_DISPLAY_MAX_CHARS - 1] + "…"
        )
        row.pick_button.setText(clipped)
        row.pick_button.setToolTip(shown_name)
        font = row.pick_button.font()
        font.setBold(index == self._shown)
        row.pick_button.setFont(font)
        row.radio.setAccessibleName(f"{spoken}を補正に使う")
        row.remove_button.setAccessibleName(f"{spoken}を消す")
        if glossary.unreadable is not None:
            row.count_label.setText(UNREADABLE_COUNT_TEXT)
        else:
            enabled_count = sum(1 for state in glossary.rows if state.enabled)
            row.count_label.setText(f"{len(glossary.rows)} 行（オン {enabled_count}）")
        # 補正に使う用語集の消すボタンは、フォーカスとツールチップを残すため無効にせず、薄くして押しても消さない
        is_active = index == self._active
        row.remove_button.setToolTip(ACTIVE_REMOVE_TOOLTIP if is_active else "")
        _dim(row.remove_button, dimmed=is_active)

    def _on_active(self, position: int, checked: bool) -> None:
        """補正に使う用語集を切り替える（前に選んでいた用語集の消すボタンが押せるようになる）。"""
        if not checked:
            return
        self._active = position
        for index in range(len(self._glossaries)):
            self._sync_list_row(index)
        self.changed.emit()

    def _show(self, position: int) -> None:
        """押した用語集の名前の欄と行の表を下に出す（切り替えても入れた値は消さない）。"""
        if position == self._shown:
            return
        self._shown = position
        self._rebuild_list()
        self._rebuild_detail()

    def _remove_glossary(self, position: int) -> None:
        """用語集を一覧から消す（CSV のファイルは消さない）。補正に使う用語集は消さない。"""
        if position == self._active:
            return
        del self._glossaries[position]
        if self._active > position:
            self._active -= 1
        # 行の表を出していた用語集を消したら、補正に使う用語集の行の表を出す
        if self._shown == position:
            self._shown = self._active
        elif self._shown > position:
            self._shown -= 1
        self._errors.clear()
        self._rebuild_list()
        self._rebuild_detail()
        self.changed.emit()

    # --- 名前の欄と行の表 ---

    def _rebuild_detail(self) -> None:
        """行の表を出している用語集の見出し・名前の欄・行の表（読めなければ理由）・行を足すボタン・凡例を作り直す。"""
        _clear_layout(self._detail_layout)
        self._inputs = {}
        self._error_labels = {}
        glossary = self._glossaries[self._shown]

        heading = QLabel(f"用語集「{_display_name(glossary.name)}」の行")
        heading.setObjectName("glossary_detail_title")
        heading.setProperty("role", "heading")
        self._detail_layout.addWidget(heading)

        name_edit = QLineEdit(glossary.name)
        name_edit.setObjectName(f"glossary_name_{self._shown}")
        name_edit.setPlaceholderText(NAME_PLACEHOLDER)
        self._add_field("名前", name_edit, ("name", None), self._detail_layout)
        name_edit.textChanged.connect(lambda text: self._on_name_changed(glossary, heading, text))

        if glossary.unreadable is not None:
            # 読めない用語集は、行の表の代わりに理由を出す（行は編集できない）
            unreadable = QLabel(
                f"この用語集の CSV を読めませんでした（{glossary.unreadable}）。"
                "保存しても、この CSV は書き換えません。"
            )
            unreadable.setObjectName("glossary_unreadable")
            unreadable.setWordWrap(True)
            self._detail_layout.addWidget(unreadable)
        elif not glossary.rows:
            empty = QLabel(EMPTY_ROWS_TEXT)
            empty.setObjectName("glossary_entries_empty")
            self._detail_layout.addWidget(empty)
        else:
            self._detail_layout.addWidget(self._build_entries(glossary))

        foot = QWidget()
        foot_line = QHBoxLayout(foot)
        foot_line.setContentsMargins(0, 0, 0, 0)
        add_button = QPushButton("行を足す")
        add_button.setObjectName("add_glossary_entry_button")
        add_button.setEnabled(glossary.unreadable is None)
        add_button.clicked.connect(lambda: self._add_entry(glossary))
        legend = QLabel(LEGEND_TEXT)
        legend.setObjectName("glossary_legend")
        legend.setProperty("role", "muted")
        foot_line.addWidget(add_button)
        foot_line.addWidget(legend, 1)
        self._detail_layout.addWidget(foot)

        # 画面を出している間に作り直した部品は、イベントループを待たずに出す（エラーの文は隠したまま）
        error_labels = set(self._error_labels.values())
        for child in self._detail_layout.parentWidget().findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        ):
            if child not in error_labels:
                child.show()
        for (position, field, row), messages in self._errors.items():
            if position == self._shown:
                self._apply_error(field, row, messages)

    def _build_entries(self, glossary: _GlossaryState) -> QFrame:
        """行の表（見出し・行ごとのオン・誤変換・正しい表記・消すボタン）を作る。"""
        table = QFrame()
        table.setObjectName("glossary_entries")
        table.setAccessibleName("用語集の行（上の行から順に置き換える）")
        column = QVBoxLayout(table)
        column.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        for text, stretch in (("使う", 0), ("誤変換", 1), ("正しい表記", 1)):
            label = QLabel(text)
            label.setProperty("role", "heading")
            head.addWidget(label, stretch)
        head.addSpacing(32)
        column.addLayout(head)
        for position, row in enumerate(glossary.rows):
            column.addWidget(self._build_entry_row(glossary, row, position))
        return table

    def _build_entry_row(self, glossary: _GlossaryState, row: _RowState, position: int) -> QWidget:
        """行の表の 1 行（オンの切り替え・誤変換の欄・正しい表記の欄・消すボタンと、欄の下のエラー）を作る。"""
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        line = QHBoxLayout()

        on_box = QCheckBox()
        on_box.setObjectName(f"glossary_entry_on_{position}")
        on_box.setAccessibleName(f"{position + 1} 行目を補正に使う")
        on_box.setChecked(row.enabled)
        wrong_edit = QLineEdit(row.wrong)
        wrong_edit.setObjectName(f"glossary_entry_wrong_{position}")
        wrong_edit.setAccessibleName(f"{position + 1} 行目の誤変換")
        right_edit = QLineEdit(row.right)
        right_edit.setObjectName(f"glossary_entry_right_{position}")
        right_edit.setAccessibleName(f"{position + 1} 行目の正しい表記")
        remove_button = QPushButton("×")
        remove_button.setObjectName(f"glossary_entry_remove_{position}")
        remove_button.setAccessibleName(f"{position + 1} 行目を消す")
        for widget in (on_box, wrong_edit, right_edit, remove_button):
            line.addWidget(widget, 1 if isinstance(widget, QLineEdit) else 0)
        column.addLayout(line)
        self._inputs[("wrong", position)] = wrong_edit
        self._inputs[("right", position)] = right_edit
        for field in ("wrong", "right"):
            error_label = QLabel()
            error_label.setTextFormat(Qt.TextFormat.PlainText)
            error_label.setProperty("role", "error")
            error_label.setWordWrap(True)
            error_label.hide()
            column.addWidget(error_label)
            self._error_labels[(field, position)] = error_label

        def sync_off_style() -> None:
            """オフの行は、誤変換と正しい表記の文字を薄くして取り消し線を引く（色だけで伝えない）。"""
            for edit in (wrong_edit, right_edit):
                font = edit.font()
                font.setStrikeOut(not row.enabled)
                edit.setFont(font)
                _dim(edit, dimmed=not row.enabled)

        def on_toggled(checked: bool) -> None:
            """オン・オフを切り替える。"""
            row.enabled = checked
            sync_off_style()
            self._sync_list_row(self._glossaries.index(glossary))
            self.changed.emit()

        def on_text(field: str, text: str) -> None:
            """誤変換・正しい表記の入力を行へ写す。"""
            if field == "wrong":
                row.wrong = text
            else:
                row.right = text
            self.changed.emit()

        sync_off_style()
        on_box.toggled.connect(on_toggled)
        wrong_edit.textChanged.connect(lambda text: on_text("wrong", text))
        right_edit.textChanged.connect(lambda text: on_text("right", text))
        remove_button.clicked.connect(lambda: self._remove_entry(glossary, row))
        return container

    def _on_name_changed(self, glossary: _GlossaryState, heading: QLabel, text: str) -> None:
        """名前の欄の入力を、一覧の名前のボタンと行の見出しにも出す。"""
        glossary.name = text
        heading.setText(f"用語集「{_display_name(text)}」の行")
        self._sync_list_row(self._glossaries.index(glossary))
        self.changed.emit()

    def _add_entry(self, glossary: _GlossaryState) -> None:
        """誤変換と正しい表記が空でオンの行を表の末尾に足し、その行の誤変換の欄へフォーカスを移す。"""
        glossary.rows.append(_RowState("", "", True))
        self._after_rows_changed(glossary)
        self._inputs[("wrong", len(glossary.rows) - 1)].setFocus()

    def _remove_entry(self, glossary: _GlossaryState, row: _RowState) -> None:
        """行を表から消す（保存するまで CSV には書かない）。"""
        glossary.rows.remove(row)
        self._after_rows_changed(glossary)

    def _after_rows_changed(self, glossary: _GlossaryState) -> None:
        """行を足す・消した後に、行の表と行の数を作り直して changed を emit する（行の添字が変わるのでエラーは消す）。"""
        self._errors.clear()
        self._rebuild_detail()
        self._sync_list_row(self._glossaries.index(glossary))
        self.changed.emit()

    def _add_field(
        self,
        label_text: str,
        edit: QLineEdit,
        key: tuple[GlossaryField, int | None],
        layout: QVBoxLayout,
    ) -> None:
        """名前つきの文字の欄と、その下のエラーの文（初めは隠す）を足して控える。"""
        label = QLabel(label_text)
        label.setProperty("role", "heading")
        label.setBuddy(edit)
        layout.addWidget(label)
        layout.addWidget(edit)
        error_label = QLabel()
        error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()
        layout.addWidget(error_label)
        self._inputs[key] = edit
        self._error_labels[key] = error_label
