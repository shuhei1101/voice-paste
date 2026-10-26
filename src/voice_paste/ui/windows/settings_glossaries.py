"""設定画面の「用語集」のまとまりに置く、用語集のプリセットの一覧と使う用語集の表、用語集の一覧と、選んだ用語集の名前の欄・行の表。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings
from voice_paste.shared.types import GlossaryEntry
from voice_paste.ui.windows.settings_edge_phrases import RowGrip
from voice_paste.ui.windows.settings_fields import set_invalid

logger = logging.getLogger(__name__)

type RowField = Literal["wrong"]
"""行の表で確かめて失敗を出す欄の種類（誤変換）。"""

type GlossaryField = Literal["name", "wrong", "right"]
"""エラーを出す・フォーカスを移す欄の種類（用語集の名前・行の誤変換・行の正しい表記）。"""

UNNAMED_TEXT: str = "（名前未入力）"
"""名前が空の用語集を、一覧と行の見出しに出す表示。"""

UNNAMED_PRESET_TEXT: str = "名前未入力のプリセット"
"""名前が空の用語集のプリセットを、一覧と見出しに出す表示。"""

UNREADABLE_COUNT_TEXT: str = "読めません"
"""CSV を読めなかった用語集の、行の数の表示。"""

LIST_COLUMN_PADDING_PX: int = 16
"""一覧の「補正に使う」の列の幅に、見出しの文字の幅へ足す余白。"""

NAME_DISPLAY_MAX_CHARS: int = 20
"""一覧の名前のボタンに出す名前の長さの上限（超えたら末尾を省く）。"""

LAST_GLOSSARY_REMOVE_TOOLTIP: str = "最後の用語集は消せません"
"""最後の 1 件の用語集の消すボタンに出すツールチップ。"""

ACTIVE_PRESET_REMOVE_TOOLTIP: str = "補正に使うプリセットは消せません"
"""補正に使うプリセットの消すボタンに出すツールチップ。"""

DIMMED_OPACITY: float = 0.4
"""押せない扱いの消すボタンと、オフの行の欄を薄くする濃さ。"""

NAME_PLACEHOLDER: str = "例: 会議用"
"""名前の欄のプレースホルダ。"""

PRESET_NAME_PLACEHOLDER: str = "例: 会議"
"""プリセットの名前の欄のプレースホルダ。"""

EMPTY_ROWS_TEXT: str = "この用語集にはまだ行がありません。"
"""行が 1 つも無い用語集の、行の表の代わりに出す文。"""

LIST_HEADINGS: tuple[str, str, str] = ("名前", "使うプリセット", "行")
"""用語集の一覧の列の見出し（名前のボタン・使うプリセット・行の数）。右端の消すボタンの列に見出しは無い。"""

PRESET_LIST_HEADINGS: tuple[str, str, str] = ("補正に使う", "名前", "用語集")
"""用語集のプリセットの一覧の列の見出し（補正に使うの選択・名前のボタン・用語集の数）。右端の消すボタンの列に見出しは無い。"""

COUNT_COLUMN_SAMPLE: str = "000 行（オン 000）"
"""行の数の列の幅を決める、いちばん長くなる表示の見本。"""

USING_COLUMN_SAMPLE: str = "使うプリセット（既定・会議）"
"""使うプリセットの列の幅を決める、見出しと並ぶ長さの見本。"""

NO_PRESET_TEXT: str = "なし"
"""どのプリセットも使っていない用語集の、使うプリセットの表示。"""

PRESET_SEPARATOR: str = "・"
"""使うプリセットの名前を結ぶ区切り。"""

LIST_NOTE_TEXT: str = "削除した用語集は、使っているプリセットからも外れる。"
"""用語集を消したときのプリセットへの影響を示す、用語集追加のボタンの右に出す説明。"""

LEGEND_TEXT: str = "上の行から順に置き換える。オフの行は補正に使わない。"
"""行の順とオン・オフが補正にどう効くかを示す凡例。"""

DELETE_NOTE_TEXT: str = "正しい表記を空にすると、誤変換を削除する。"
"""正しい表記を空にした行が誤変換を消すことを伝える、名前の欄の下に出す説明。"""

PRESET_RULE_TEXT: str = (
    "上の用語集から順に当てる。同じ誤変換は上の用語集の行が当たる。行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。"
)
"""使う用語集の当てる順と並べ替えの操作を示す凡例。"""

PRESET_EMPTY_TEXT: str = "使う用語集がありません。このプリセットでは何も置き換えません。"
"""使う用語集が 0 件のプリセットの、表の代わりに出す文。"""

PRESET_ALL_USED_TEXT: str = "全ての用語集を使っています。"
"""用語集の一覧の全てをプリセットが使っているときの、追加の欄の代わりに出す文。"""

USES_ACCESSIBLE_NAME: str = "プリセットで使う用語集（上の用語集から順に当てる）"
"""使う用語集の表の読み上げの名前。"""

USES_HEADINGS: tuple[str, str, str] = ("順", "用語集", "行")
"""使う用語集の表の列の見出し（つまみと外すボタンの列に見出しは出さない）。"""

ROW_ERROR_MESSAGES: dict[str, str] = {"wrong": "誤変換を入れてください。"}
"""誤変換だけが空の行の、誤変換の欄の下に出すエラーの文言。"""


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
    """開いたときに読んだ行（保存した後は保存した行）。足してまだ保存していない用語集と、読めなかった用語集は None。"""
    unreadable: str | None = None
    """CSV を読めなかった理由。読めたら None。"""


@dataclass(eq=False)
class _PresetState:
    """一覧の用語集のプリセット 1 つの、今の入力。"""

    ident: int
    """プリセットの識別（開いたときの何件目か。足したプリセットは開いたときの件数から続く番号）。変えた欄の数えのキーに使う。"""
    name: str
    paths: list[Path]
    """使う用語集の CSV の場所の並び（用語集の名前を変えても指す先が変わらない）。"""


@dataclass
class _ListRow:
    """用語集の一覧の 1 行の部品。"""

    pick_button: QPushButton
    using_label: QLabel
    count_label: QLabel
    remove_button: QPushButton


@dataclass
class _PresetListRow:
    """用語集のプリセットの一覧の 1 行の部品。"""

    radio: QRadioButton
    pick_button: QPushButton
    count_label: QLabel
    remove_button: QPushButton


class _UsedRemoveButton(QPushButton):
    """使う用語集の表の外すボタン。フォーカスがあるとき Alt+↑ / Alt+↓ で行を動かす依頼を出す。"""

    move_requested = Signal(int)
    """行を動かす依頼（-1 は上へ、1 は下へ）。"""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt の名前
        """Alt+↑ / Alt+↓ なら行を動かす依頼を出し、それ以外はボタンの操作として扱う。"""
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Up:
                self.move_requested.emit(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down:
                self.move_requested.emit(1)
                event.accept()
                return
        super().keyPressEvent(event)


def find_glossary_row_errors(entries: Sequence[GlossaryEntry]) -> list[tuple[int, RowField]]:
    """用語集の行のうち、正しい表記が入っていて誤変換が空の行と、空の側の項目を返す。オフの行も確かめる。"""
    errors: list[tuple[int, RowField]] = []
    for position, entry in enumerate(entries):
        # 誤変換だけが空: 誤変換の欄（両方が空の行と、正しい表記だけが空の行は返さない）
        if not entry.wrong and entry.right:
            errors.append((position, "wrong"))
    return errors


def _display_name(name: str) -> str:
    """名前の表示（前後の空白を除き、空なら「（名前未入力）」）を返す。"""
    return name.strip() or UNNAMED_TEXT


def _spoken_name(name: str) -> str:
    """読み上げの名前に使う用語集の呼び方（名前が空なら「名前未入力の用語集」）を返す。"""
    return name.strip() or "名前未入力の用語集"


def _preset_display_name(name: str) -> str:
    """プリセットの名前の表示（前後の空白を除き、空なら「名前未入力のプリセット」）を返す。"""
    return name.strip() or UNNAMED_PRESET_TEXT


def _clip(text: str) -> str:
    """名前の表示を、長ければ末尾を省いて 1 行に収める。"""
    if len(text) <= NAME_DISPLAY_MAX_CHARS:
        return text
    return text[: NAME_DISPLAY_MAX_CHARS - 1] + "…"


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
    """設定画面の「用語集」のまとまりに置く、用語集のプリセットの一覧と使う用語集の表、用語集の一覧と選んだ用語集の名前の欄・行の表。

    足す・消す・並べ替え・入力はこの部品の中だけを変え、settings.toml と CSV へは設定画面の保存で書く。
    """

    changed = Signal()
    """用語集・行・プリセットを足す・消す、補正に使うプリセットの切り替え、プリセットの用語集の追加・外し・並べ替え、欄の入力、行のオン・オフで値が変わった。"""

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
        self._presets: list[_PresetState] = []
        self._next_preset_ident = 0
        self._shown = 0
        """行の表を出している用語集の添字。"""
        self._shown_preset = 0
        """使う用語集の表を出しているプリセットの添字。"""
        self._active_preset = 0
        """補正に使うプリセットの添字。"""
        self._list_rows: list[_ListRow] = []
        self._preset_rows: list[_PresetListRow] = []
        self._uses_rows: list[QFrame] = []
        """使う用語集の表に出している行の枠（つまみを離した位置から移し先を決めるのに使う）。"""
        self._active_group = QButtonGroup(self)
        self._errors: dict[tuple[int, GlossaryField, int | None], list[str]] = {}
        """出すエラー（用語集の何件目か・項目・何行目か → 文言）。行の表を切り替えても残す。"""
        self._preset_errors: dict[int, list[str]] = {}
        """出すプリセットの名前のエラー（プリセットの何件目か → 文言）。使う用語集の表を切り替えても残す。"""
        self._inputs: dict[tuple[GlossaryField, int | None], QLineEdit] = {}
        self._error_labels: dict[tuple[GlossaryField, int | None], QLabel] = {}
        self._preset_name_edit: QLineEdit | None = None
        self._preset_error_label: QLabel | None = None
        self.setObjectName("glossary_panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        preset_heading = QLabel("用語集のプリセット")
        preset_heading.setProperty("role", "heading")
        outer.addWidget(preset_heading)
        preset_list_frame = QFrame()
        preset_list_frame.setObjectName("glossary_preset_list")
        preset_list_frame.setAccessibleName("用語集のプリセットの一覧（補正に使うプリセットを 1 つ選ぶ）")
        self._preset_list_layout = QVBoxLayout(preset_list_frame)
        outer.addWidget(preset_list_frame)
        add_preset_button = QPushButton("プリセット追加")
        add_preset_button.setObjectName("add_glossary_preset_button")
        add_preset_button.clicked.connect(self.add_glossary_preset)
        outer.addWidget(add_preset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        preset_detail_frame = QFrame()
        preset_detail_frame.setProperty("role", "surface")
        self._preset_detail_layout = QVBoxLayout(preset_detail_frame)
        outer.addWidget(preset_detail_frame)

        list_heading = QLabel("用語集の一覧")
        list_heading.setProperty("role", "heading")
        outer.addWidget(list_heading)
        list_frame = QFrame()
        list_frame.setObjectName("glossary_list")
        list_frame.setAccessibleName("用語集の一覧")
        self._list_layout = QVBoxLayout(list_frame)
        outer.addWidget(list_frame)
        add_button = QPushButton("用語集追加")
        add_button.setObjectName("add_glossary_button")
        add_button.clicked.connect(self.add_glossary)
        list_note = QLabel(LIST_NOTE_TEXT)
        list_note.setObjectName("glossary_list_note")
        list_note.setProperty("role", "muted")
        list_foot = QHBoxLayout()
        list_foot.addWidget(add_button)
        list_foot.addWidget(list_note, 1)
        outer.addLayout(list_foot)
        detail_frame = QFrame()
        detail_frame.setProperty("role", "surface")
        self._detail_layout = QVBoxLayout(detail_frame)
        outer.addWidget(detail_frame)

    # --- 値の出し入れ ---

    def set_glossaries(
        self,
        glossaries: Sequence[GlossarySettings],
        presets: Sequence[GlossaryPresetSettings],
        active_preset: str,
    ) -> None:
        """渡した用語集とプリセットで一覧を作り直し、用語集ごとに行を読んで開いたときの行として控え、補正に使うプリセットの使う用語集の表と、その 1 つ目の用語集の行の表を出す。"""
        # 1. 用語集ごとに行を読んで一覧を作る（読めない用語集は理由を控えて一覧に残す）
        self._glossaries = []
        for glossary in glossaries:
            try:
                rows = self._read_glossary(glossary.path)
            except GlossaryReadError as error:
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

        # 2. プリセットごとに、使う用語集の名前をその用語集の CSV の場所に置き換える
        path_by_name = {glossary.name: glossary.path for glossary in glossaries}
        self._presets = [
            _PresetState(
                ident,
                preset.name,
                [path_by_name[name] for name in preset.glossaries if name in path_by_name],
            )
            for ident, preset in enumerate(presets)
        ]
        self._next_preset_ident = len(self._presets)

        # 3. 補正に使うプリセットを選び、その使う用語集の表と、1 つ目の用語集（無ければ一覧の 1 件目）の行の表を出す
        preset_names = [preset.name for preset in presets]
        self._active_preset = preset_names.index(active_preset) if active_preset in preset_names else 0
        self._shown_preset = self._active_preset
        first_paths = self._presets[self._active_preset].paths
        self._shown = self._position_of(first_paths[0]) if first_paths else 0
        self._errors.clear()
        self._preset_errors.clear()
        self._rebuild_preset_list()
        self._rebuild_preset_detail()
        self._rebuild_list()
        self._rebuild_detail()

    def collect(self) -> list[dict[str, Any]]:
        """今の並びの用語集を、settings.toml と同じ形の dict（name・path）の並びにする。name は前後の空白を除く。"""
        return [
            {"name": glossary.name.strip(), "path": glossary.path} for glossary in self._glossaries
        ]

    def collect_presets(self) -> list[dict[str, Any]]:
        """今の並びの用語集のプリセットを、settings.toml と同じ形の dict（name・glossaries）の並びにする。glossaries は使う用語集の今の名前を表の順に並べる。"""
        return [
            {
                "name": preset.name.strip(),
                "glossaries": [self._glossary_at(path).name.strip() for path in preset.paths],
            }
            for preset in self._presets
        ]

    def active_preset_name(self) -> str:
        """補正に使うプリセットに選んでいるプリセットの、今の名前の欄の値（前後の空白を除く）を返す。"""
        return self._presets[self._active_preset].name.strip()

    def changed_rows(self) -> dict[Path, list[GlossaryEntry]]:
        """行を変えた用語集と足した用語集だけの、CSV の場所 → 行（表の順。両方が空の行は除く）を返す。"""
        changed: dict[Path, list[GlossaryEntry]] = {}
        for glossary in self._glossaries:
            # 読めなかった用語集は、保存してもその CSV に触れない
            if glossary.unreadable is not None:
                continue
            entries = self._filled_entries(glossary)
            # 足した用語集か、開いたときと行が違う用語集だけを書き戻す（名前だけ変えた用語集は入らない）
            if glossary.original is None or entries != glossary.original:
                changed[glossary.path] = entries
        return changed

    def change_values(self) -> dict[str, object]:
        """変えた欄の数えに使う値を、用語集 1 つ = 1 キー、用語集のプリセット 1 つ = 1 キーと、補正に使うプリセットの 1 キーで返す。"""
        values: dict[str, object] = {}
        for glossary in self._glossaries:
            # 読めなかった用語集は行を比べない（保存してもその CSV に触れない）
            rows = None if glossary.unreadable is not None else self._filled_entries(glossary)
            values[f"glossaries[{glossary.path}]"] = (glossary.name.strip(), rows)
        # プリセットは名前と使う用語集の場所の並びで持ち、用語集の名前を変えてもプリセットの変更として数えない
        for preset in self._presets:
            values[f"glossary_presets[{preset.ident}]"] = (preset.name.strip(), list(preset.paths))
        # 補正に使うプリセットは名前でなく識別で持ち、名前を変えても切り替えとして数えない
        values["active_glossary_preset"] = self._presets[self._active_preset].ident
        return values

    def mark_saved(self) -> None:
        """書き戻す用語集を決める基準（開いたときの行）を、今の表の行へ置き直す。保存が書けた後に呼ぶ。"""
        for glossary in self._glossaries:
            # 読めなかった用語集は、保存してもその CSV に触れないのでそのまま
            if glossary.unreadable is not None:
                continue
            # 足した用語集も、保存した行を基準にする（次の changed_rows は行を変えなければ入れない）
            glossary.original = self._filled_entries(glossary)

    def row_errors(self) -> list[tuple[int, int, RowField]]:
        """読めた全ての用語集の行を確かめ、誤変換だけが空の行の（用語集の何件目か, 何行目か, 空の側の項目）を返す。"""
        errors: list[tuple[int, int, RowField]] = []
        for position, glossary in enumerate(self._glossaries):
            if glossary.unreadable is not None:
                continue
            errors.extend(
                (position, row, field)
                for row, field in find_glossary_row_errors(self._entries(glossary))
            )
        return errors

    @classmethod
    def _filled_entries(cls, glossary: _GlossaryState) -> list[GlossaryEntry]:
        """用語集の今の行から、両方が空の行を除いた並びにする。"""
        return [entry for entry in cls._entries(glossary) if entry.wrong or entry.right]

    @staticmethod
    def _entries(glossary: _GlossaryState) -> list[GlossaryEntry]:
        """用語集の今の行を、前後の空白を除いた GlossaryEntry の並びにする。"""
        return [
            GlossaryEntry(wrong=row.wrong.strip(), right=row.right.strip(), enabled=row.enabled)
            for row in glossary.rows
        ]

    # --- 操作 ---

    def add_glossary(self) -> None:
        """末尾に名前が空で行の無い用語集を足し、その行の表を出して名前の欄へフォーカスを移し、changed を emit する。どのプリセットの使う用語集にも入れない。"""
        path = self._new_glossary_path([glossary.path for glossary in self._glossaries])
        self._glossaries.append(_GlossaryState("", path, [], None))
        self._shown = len(self._glossaries) - 1
        self._rebuild_preset_detail()
        self._rebuild_list()
        self._rebuild_detail()
        self._inputs[("name", None)].setFocus()
        self.changed.emit()

    def add_glossary_preset(self) -> None:
        """末尾に名前が空で使う用語集の無いプリセットを足し、その使う用語集の表を出して名前の欄へフォーカスを移し、changed を emit する。"""
        self._presets.append(_PresetState(self._next_preset_ident, "", []))
        self._next_preset_ident += 1
        self._shown_preset = len(self._presets) - 1
        self._rebuild_preset_list()
        self._rebuild_preset_detail()
        self._rebuild_list()
        if self._preset_name_edit is not None:
            self._preset_name_edit.setFocus()
        self.changed.emit()

    def focus_field(self, position: int, field: GlossaryField, *, row: int | None = None) -> None:
        """用語集の何件目かと項目（と行）で欄を探し、その用語集の行の表を出してフォーカスを移す。"""
        self._show(position)
        edit = self._inputs.get((field, row))
        if edit is not None:
            edit.setFocus()

    def focus_preset_name(self, position: int) -> None:
        """用語集のプリセットの何件目かでその使う用語集の表を出し、名前の欄へフォーカスを移す。"""
        self._show_preset(position)
        if self._preset_name_edit is not None:
            self._preset_name_edit.setFocus()

    def show_error(
        self, position: int, field: GlossaryField, message: str, *, row: int | None = None
    ) -> None:
        """用語集の何件目かと項目（と行）の欄の下にエラーを出し、欄をエラーの見た目にする。"""
        self._errors.setdefault((position, field, row), []).append(message)
        if position == self._shown:
            self._apply_error(field, row, self._errors[(position, field, row)])

    def show_preset_error(self, position: int, message: str) -> None:
        """用語集のプリセットの何件目かの名前の欄の下にエラーを出し、欄をエラーの見た目にする（その表を出していないときは、表を出したときに出す）。"""
        self._preset_errors.setdefault(position, []).append(message)
        if position == self._shown_preset:
            self._apply_preset_error()

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て消す。"""
        self._errors.clear()
        self._preset_errors.clear()
        for key, label in self._error_labels.items():
            label.clear()
            label.hide()
            set_invalid(self._inputs[key], invalid=False)
        if self._preset_error_label is not None and self._preset_name_edit is not None:
            self._preset_error_label.clear()
            self._preset_error_label.hide()
            set_invalid(self._preset_name_edit, invalid=False)

    def _apply_error(self, field: GlossaryField, row: int | None, messages: list[str]) -> None:
        """今出している行の表の欄の下にエラーを出し、欄を赤くする。"""
        label = self._error_labels.get((field, row))
        edit = self._inputs.get((field, row))
        if label is None or edit is None:
            return
        label.setText("\n".join(messages))
        label.show()
        set_invalid(edit, invalid=True)

    # --- 用語集のプリセットの一覧と使う用語集の表 ---

    def _rebuild_preset_list(self) -> None:
        """用語集のプリセットの一覧（補正に使うプリセットの選択・名前のボタン・用語集の数・消すボタン）を作り直す。"""
        for preset_row in self._preset_rows:
            self._active_group.removeButton(preset_row.radio)
        _clear_layout(self._preset_list_layout)
        self._preset_rows = []
        # 見出しの行とプリセットの行で、列の幅をそろえる
        metrics = self.fontMetrics()
        active_width = metrics.horizontalAdvance(PRESET_LIST_HEADINGS[0]) + LIST_COLUMN_PADDING_PX
        count_width = metrics.horizontalAdvance("000 件") + LIST_COLUMN_PADDING_PX
        remove_width = QPushButton("×").sizeHint().width()
        self._preset_list_layout.addWidget(
            self._build_heading_row(
                PRESET_LIST_HEADINGS, (active_width, None, count_width), remove_width
            )
        )
        for index in range(len(self._presets)):
            # 使う用語集の表を出しているプリセットの行は、背景を変えて示す
            frame = QFrame()
            if index == self._shown_preset:
                frame.setProperty("role", "surface")
            line = QHBoxLayout(frame)
            line.setContentsMargins(4, 2, 4, 2)

            radio = QRadioButton()
            radio_cell = QWidget()
            radio_cell.setFixedWidth(active_width)
            cell_line = QHBoxLayout(radio_cell)
            cell_line.setContentsMargins(0, 0, 0, 0)
            cell_line.addWidget(radio, alignment=Qt.AlignmentFlag.AlignCenter)
            radio.setObjectName(f"glossary_preset_active_{index}")
            radio.setChecked(index == self._active_preset)
            radio.toggled.connect(
                lambda checked, position=index: self._on_active_preset(position, checked)
            )
            self._active_group.addButton(radio)
            pick_button = QPushButton()
            pick_button.setObjectName(f"glossary_preset_pick_{index}")
            pick_button.setFlat(True)
            pick_button.clicked.connect(
                lambda _checked=False, position=index: self._show_preset(position)
            )
            count_label = QLabel()
            count_label.setObjectName(f"glossary_preset_count_{index}")
            count_label.setFixedWidth(count_width)
            remove_button = QPushButton("×")
            remove_button.setObjectName(f"glossary_preset_remove_{index}")
            remove_button.setFixedWidth(remove_width)
            remove_button.clicked.connect(
                lambda _checked=False, position=index: self._remove_preset(position)
            )
            line.addWidget(radio_cell)
            line.addWidget(pick_button, 1)
            line.addWidget(count_label)
            line.addWidget(remove_button)
            self._preset_list_layout.addWidget(frame)
            frame.show()
            self._preset_rows.append(
                _PresetListRow(radio, pick_button, count_label, remove_button)
            )
            self._sync_preset_row(index)

    def _sync_preset_row(self, index: int) -> None:
        """プリセットの一覧の 1 行の表示（名前・用語集の数・読み上げの名前・消すボタンの扱い）を、今の入力に合わせる。"""
        preset = self._presets[index]
        row = self._preset_rows[index]
        shown_name = _preset_display_name(preset.name)
        row.pick_button.setText(_clip(shown_name))
        row.pick_button.setToolTip(shown_name)
        font = row.pick_button.font()
        font.setBold(index == self._shown_preset)
        row.pick_button.setFont(font)
        row.radio.setAccessibleName(f"{shown_name}を補正に使う")
        row.remove_button.setAccessibleName(f"{shown_name}を削除")
        row.count_label.setText(f"{len(preset.paths)} 件")
        # 補正に使うプリセットの消すボタンは、フォーカスとツールチップを残すため無効にせず、薄くして押しても消さない
        is_active = index == self._active_preset
        row.remove_button.setToolTip(ACTIVE_PRESET_REMOVE_TOOLTIP if is_active else "")
        _dim(row.remove_button, dimmed=is_active)

    def _on_active_preset(self, position: int, checked: bool) -> None:
        """補正に使うプリセットを切り替える（前に選んでいたプリセットの消すボタンが押せるようになる）。"""
        if not checked:
            return
        self._active_preset = position
        for index in range(len(self._presets)):
            self._sync_preset_row(index)
        self.changed.emit()

    def _show_preset(self, position: int) -> None:
        """押したプリセットの名前の欄と使う用語集の表を下に出す（切り替えても入れた値は消さない）。"""
        if position == self._shown_preset:
            return
        self._shown_preset = position
        self._rebuild_preset_list()
        self._rebuild_preset_detail()

    def _remove_preset(self, position: int) -> None:
        """用語集のプリセットを一覧から消す。補正に使うプリセットは消さない。"""
        if position == self._active_preset:
            return
        del self._presets[position]
        if self._active_preset > position:
            self._active_preset -= 1
        # 表を出していたプリセットを消したら、補正に使うプリセットの表を出す
        if self._shown_preset == position:
            self._shown_preset = self._active_preset
        elif self._shown_preset > position:
            self._shown_preset -= 1
        self._preset_errors.clear()
        self._rebuild_preset_list()
        self._rebuild_preset_detail()
        self._rebuild_list()
        self.changed.emit()

    def _rebuild_preset_detail(self) -> None:
        """表を出しているプリセットの見出し・名前の欄・使う用語集の表（無ければ文）・追加の欄・凡例を作り直す。"""
        _clear_layout(self._preset_detail_layout)
        preset = self._presets[self._shown_preset]

        heading = QLabel()
        heading.setObjectName("glossary_preset_detail_title")
        heading.setProperty("role", "heading")
        self._sync_preset_heading(heading, preset)
        self._preset_detail_layout.addWidget(heading)

        name_edit = QLineEdit(preset.name)
        name_edit.setObjectName(f"glossary_preset_name_{self._shown_preset}")
        name_edit.setPlaceholderText(PRESET_NAME_PLACEHOLDER)
        name_label = QLabel("名前")
        name_label.setProperty("role", "heading")
        name_label.setBuddy(name_edit)
        error_label = QLabel()
        error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()
        self._preset_detail_layout.addWidget(name_label)
        self._preset_detail_layout.addWidget(name_edit)
        self._preset_detail_layout.addWidget(error_label)
        self._preset_name_edit = name_edit
        self._preset_error_label = error_label
        name_edit.textChanged.connect(lambda text: self._on_preset_name_changed(preset, heading, text))

        if preset.paths:
            self._preset_detail_layout.addWidget(self._build_uses(preset))
        else:
            empty = QLabel(PRESET_EMPTY_TEXT)
            empty.setObjectName("glossary_preset_glossaries_empty")
            self._preset_detail_layout.addWidget(empty)

        unused = [glossary for glossary in self._glossaries if glossary.path not in preset.paths]
        if unused:
            self._preset_detail_layout.addWidget(self._build_add_row(preset, unused))
        else:
            all_used = QLabel(PRESET_ALL_USED_TEXT)
            all_used.setObjectName("glossary_preset_glossaries_all")
            all_used.setProperty("role", "muted")
            self._preset_detail_layout.addWidget(all_used)

        rule_note = QLabel(PRESET_RULE_TEXT)
        rule_note.setObjectName("glossary_preset_rule_note")
        rule_note.setProperty("role", "muted")
        rule_note.setWordWrap(True)
        self._preset_detail_layout.addWidget(rule_note)

        # 画面を出している間に作り直した部品は、イベントループを待たずに出す（エラーの文は隠したまま）
        for child in self._preset_detail_layout.parentWidget().findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        ):
            if child is not error_label:
                child.show()
        self._apply_preset_error()

    @staticmethod
    def _sync_preset_heading(heading: QLabel, preset: _PresetState) -> None:
        """使う用語集の表の見出しを、プリセットの今の名前に合わせる。"""
        name = preset.name.strip()
        heading.setText(f"プリセット「{name}」で使う用語集" if name else f"{UNNAMED_PRESET_TEXT}で使う用語集")

    def _apply_preset_error(self) -> None:
        """使う用語集の表を出しているプリセットの名前の欄の下にエラーを出し、欄を赤くする。"""
        messages = self._preset_errors.get(self._shown_preset)
        if not messages or self._preset_name_edit is None or self._preset_error_label is None:
            return
        self._preset_error_label.setText("\n".join(messages))
        self._preset_error_label.show()
        set_invalid(self._preset_name_edit, invalid=True)

    def _on_preset_name_changed(self, preset: _PresetState, heading: QLabel, text: str) -> None:
        """プリセットの名前の欄の入力を、一覧の名前のボタンと見出しと、用語集の一覧の使うプリセットにも出す。"""
        preset.name = text
        self._sync_preset_heading(heading, preset)
        self._sync_preset_row(self._presets.index(preset))
        for index in range(len(self._glossaries)):
            self._sync_list_row(index)
        self.changed.emit()

    def _build_uses(self, preset: _PresetState) -> QFrame:
        """使う用語集の表（見出し・行ごとのつまみ・順・用語集・行の数・外すボタン）を作る。"""
        table = QFrame()
        table.setObjectName("glossary_preset_glossaries")
        table.setAccessibleName(USES_ACCESSIBLE_NAME)
        column = QVBoxLayout(table)
        column.setContentsMargins(0, 0, 0, 0)
        self._uses_rows = []
        head = QHBoxLayout()
        grip_gap = QWidget()
        grip_gap.setFixedWidth(RowGrip().sizeHint().width())
        head.addWidget(grip_gap)
        for text, stretch in zip(USES_HEADINGS, (0, 1, 0), strict=True):
            label = QLabel(text)
            label.setProperty("role", "heading")
            head.addWidget(label, stretch)
        head.addSpacing(32)
        column.addLayout(head)
        for position, path in enumerate(preset.paths):
            column.addWidget(self._build_use_row(preset, path, position))
        return table

    def _build_use_row(self, preset: _PresetState, path: Path, position: int) -> QFrame:
        """使う用語集の表の 1 行（つまみ・順・用語集の名前・行の数・外すボタン）を作る。"""
        glossary = self._glossary_at(path)
        shown_name = _display_name(glossary.name)
        frame = QFrame()
        line = QHBoxLayout(frame)
        line.setContentsMargins(4, 2, 4, 2)

        grip = RowGrip()
        grip.setObjectName(f"glossary_preset_glossary_grip_{position}")
        grip.setAccessibleName(f"{shown_name}を動かす")
        order_label = QLabel(str(position + 1))
        name_label = QLabel(_clip(shown_name))
        name_label.setToolTip(shown_name)
        count_label = QLabel(
            UNREADABLE_COUNT_TEXT if glossary.unreadable is not None else f"{len(glossary.rows)} 行"
        )
        remove_button = _UsedRemoveButton("×")
        remove_button.setObjectName(f"glossary_preset_glossary_remove_{position}")
        remove_button.setAccessibleName(f"{shown_name}を外す")
        line.addWidget(grip)
        line.addWidget(order_label)
        line.addWidget(name_label, 1)
        line.addWidget(count_label)
        line.addWidget(remove_button)

        grip.released.connect(lambda global_y: self._drop_use(preset, frame, global_y))
        remove_button.move_requested.connect(
            lambda delta: self._move_use(preset, position, position + delta)
        )
        remove_button.clicked.connect(lambda: self._detach_use(preset, position))
        self._uses_rows.append(frame)
        return frame

    def _build_add_row(self, preset: _PresetState, unused: Sequence[_GlossaryState]) -> QWidget:
        """プリセットがまだ使っていない用語集の選択と追加ボタンを作る。"""
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        label = QLabel("追加する用語集")
        combo = QComboBox()
        combo.setObjectName("glossary_preset_glossary_select")
        label.setBuddy(combo)
        for glossary in unused:
            combo.addItem(_display_name(glossary.name), str(glossary.path))
        add_button = QPushButton("追加")
        add_button.setObjectName("glossary_preset_glossary_add")
        add_button.clicked.connect(lambda: self._attach_use(preset, combo))
        line.addWidget(label)
        line.addWidget(combo, 1)
        line.addWidget(add_button)
        return row

    def _attach_use(self, preset: _PresetState, combo: QComboBox) -> None:
        """選んだ用語集を使う用語集の表の末尾に足し、選択肢から除く。"""
        selected = combo.currentData()
        if selected is None:
            return
        preset.paths.append(Path(str(selected)))
        self._after_uses_changed(preset)

    def _detach_use(self, preset: _PresetState, position: int) -> None:
        """用語集をこのプリセットから外す（用語集そのものは消さず、追加する用語集の選択肢へ戻す）。"""
        del preset.paths[position]
        self._after_uses_changed(preset)

    def _move_use(self, preset: _PresetState, position: int, target: int) -> None:
        """使う用語集の行を target の位置へ動かし、動かした行の外すボタンへフォーカスを移して読み上げに伝える。"""
        # 先頭より上・末尾より下へは動かさない
        if position == target or not 0 <= target < len(preset.paths):
            return
        preset.paths.insert(target, preset.paths.pop(position))
        self._after_uses_changed(preset)
        moved_button = self._preset_detail_layout.parentWidget().findChild(
            QPushButton, f"glossary_preset_glossary_remove_{target}"
        )
        if moved_button is not None:
            moved_button.setFocus()
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(moved_button, f"{target + 1} 行目へ動かしました")
            )

    def _drop_use(self, preset: _PresetState, frame: QFrame, global_y: int) -> None:
        """つまみを離した縦の位置から、行の移し先（他の行のうち、中心がそれより上にある数）を決めて動かす。"""
        position = self._uses_rows.index(frame)
        target = sum(
            1
            for index, row in enumerate(self._uses_rows)
            if index != position
            and row.mapToGlobal(row.rect().center()).y() < global_y
        )
        self._move_use(preset, position, target)

    def _after_uses_changed(self, preset: _PresetState) -> None:
        """使う用語集を足す・外す・動かした後に、使う用語集の表と一覧の表示を作り直して changed を emit する。"""
        self._rebuild_preset_detail()
        self._sync_preset_row(self._presets.index(preset))
        for index in range(len(self._glossaries)):
            self._sync_list_row(index)
        self.changed.emit()

    # --- 用語集の一覧 ---

    def _rebuild_list(self) -> None:
        """用語集の一覧（名前のボタン・使うプリセット・行の数・消すボタン）を作り直す。"""
        _clear_layout(self._list_layout)
        self._list_rows = []
        # 見出しの行と用語集の行で、列の幅をそろえる
        metrics = self.fontMetrics()
        using_width = metrics.horizontalAdvance(USING_COLUMN_SAMPLE)
        count_width = metrics.horizontalAdvance(COUNT_COLUMN_SAMPLE)
        remove_width = QPushButton("×").sizeHint().width()
        self._list_layout.addWidget(
            self._build_heading_row(LIST_HEADINGS, (None, using_width, count_width), remove_width)
        )
        for index in range(len(self._glossaries)):
            # 行の表を出している用語集の行は、背景を変えて示す
            frame = QFrame()
            if index == self._shown:
                frame.setProperty("role", "surface")
            line = QHBoxLayout(frame)
            line.setContentsMargins(4, 2, 4, 2)

            pick_button = QPushButton()
            pick_button.setObjectName(f"glossary_pick_{index}")
            pick_button.setFlat(True)
            pick_button.clicked.connect(lambda _checked=False, position=index: self._show(position))
            using_label = QLabel()
            using_label.setObjectName(f"glossary_presets_using_{index}")
            using_label.setFixedWidth(using_width)
            count_label = QLabel()
            count_label.setObjectName(f"glossary_count_{index}")
            count_label.setFixedWidth(count_width)
            remove_button = QPushButton("×")
            remove_button.setObjectName(f"glossary_remove_{index}")
            remove_button.setFixedWidth(remove_width)
            remove_button.clicked.connect(
                lambda _checked=False, position=index: self._remove_glossary(position)
            )
            line.addWidget(pick_button, 1)
            line.addWidget(using_label)
            line.addWidget(count_label)
            line.addWidget(remove_button)
            self._list_layout.addWidget(frame)
            frame.show()
            self._list_rows.append(_ListRow(pick_button, using_label, count_label, remove_button))
            self._sync_list_row(index)

    @staticmethod
    def _build_heading_row(
        headings: tuple[str, str, str], widths: tuple[int | None, int | None, int | None], remove_width: int
    ) -> QWidget:
        """一覧の列の見出しの行を作る。幅は一覧の行の列とそろえる。"""
        heading = QWidget()
        line = QHBoxLayout(heading)
        line.setContentsMargins(4, 2, 4, 2)
        for text, width in zip(headings, widths, strict=True):
            label = QLabel(text)
            label.setProperty("role", "heading")
            if width is None:
                line.addWidget(label, 1)
            else:
                label.setFixedWidth(width)
                line.addWidget(label)
        spacer = QWidget()
        spacer.setFixedWidth(remove_width)
        line.addWidget(spacer)
        heading.show()
        return heading

    def _sync_list_row(self, index: int) -> None:
        """用語集の一覧の 1 行の表示（名前・使うプリセット・行の数・読み上げの名前・消すボタンの扱い）を、今の入力に合わせる。"""
        glossary = self._glossaries[index]
        row = self._list_rows[index]
        shown_name = _display_name(glossary.name)
        spoken = _spoken_name(glossary.name)
        row.pick_button.setText(_clip(shown_name))
        row.pick_button.setToolTip(shown_name)
        font = row.pick_button.font()
        font.setBold(index == self._shown)
        row.pick_button.setFont(font)
        row.remove_button.setAccessibleName(f"{spoken}を削除")
        using = PRESET_SEPARATOR.join(
            _preset_display_name(preset.name)
            for preset in self._presets
            if glossary.path in preset.paths
        )
        row.using_label.setText(using or NO_PRESET_TEXT)
        if glossary.unreadable is not None:
            row.count_label.setText(UNREADABLE_COUNT_TEXT)
        else:
            enabled_count = sum(1 for state in glossary.rows if state.enabled)
            row.count_label.setText(f"{len(glossary.rows)} 行（オン {enabled_count}）")
        # 最後の 1 件の用語集の消すボタンは、フォーカスとツールチップを残すため無効にせず、薄くして押しても消さない
        is_last = len(self._glossaries) == 1
        row.remove_button.setToolTip(LAST_GLOSSARY_REMOVE_TOOLTIP if is_last else "")
        _dim(row.remove_button, dimmed=is_last)

    def _show(self, position: int) -> None:
        """押した用語集の名前の欄と行の表を下に出す（切り替えても入れた値は消さない）。"""
        if position == self._shown:
            return
        self._shown = position
        self._rebuild_list()
        self._rebuild_detail()

    def _remove_glossary(self, position: int) -> None:
        """用語集を一覧と全てのプリセットの使う用語集から消す（CSV のファイルは消さない）。最後の 1 件は消さない。"""
        if len(self._glossaries) == 1:
            return
        removed = self._glossaries.pop(position)
        for preset in self._presets:
            preset.paths = [path for path in preset.paths if path != removed.path]
        # 行の表を出していた用語集を消したら、一覧の 1 件目の行の表を出す
        if self._shown == position:
            self._shown = 0
        elif self._shown > position:
            self._shown -= 1
        self._errors.clear()
        self._rebuild_preset_list()
        self._rebuild_preset_detail()
        self._rebuild_list()
        self._rebuild_detail()
        self.changed.emit()

    def _position_of(self, path: Path) -> int:
        """CSV の場所から、一覧の用語集の添字を返す。"""
        return next(
            index for index, glossary in enumerate(self._glossaries) if glossary.path == path
        )

    def _glossary_at(self, path: Path) -> _GlossaryState:
        """CSV の場所から、一覧の用語集を返す。"""
        return self._glossaries[self._position_of(path)]

    # --- 名前の欄と行の表 ---

    def _rebuild_detail(self) -> None:
        """行の表を出している用語集の見出し・名前の欄・誤変換を削除する行の説明・行の表（読めなければ理由）・行の追加ボタン・凡例を作り直す。"""
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
        else:
            # 読めた用語集は、正しい表記を空にした行が誤変換を消すことを名前の欄の下に出す
            delete_note = QLabel(DELETE_NOTE_TEXT)
            delete_note.setObjectName("glossary_delete_note")
            delete_note.setProperty("role", "muted")
            self._detail_layout.addWidget(delete_note)
            if not glossary.rows:
                empty = QLabel(EMPTY_ROWS_TEXT)
                empty.setObjectName("glossary_entries_empty")
                self._detail_layout.addWidget(empty)
            else:
                self._detail_layout.addWidget(self._build_entries(glossary))

        foot = QWidget()
        foot_line = QHBoxLayout(foot)
        foot_line.setContentsMargins(0, 0, 0, 0)
        add_button = QPushButton("行追加")
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
        remove_button.setAccessibleName(f"{position + 1} 行目を削除")
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
        # 使う用語集の表と追加する用語集の選択にも、新しい名前を出す
        self._rebuild_preset_detail()
        for index in range(len(self._glossaries)):
            self._sync_list_row(index)
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
