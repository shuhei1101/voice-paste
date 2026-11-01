"""設定画面の「表記のヒント」のまとまりに置く、有効なヒントの長さとヒントのプリセットの一覧。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.settings import HINT_MAX_BYTES, HintPresetSettings, join_hint_words
from voice_paste.ui.windows.settings_fields import set_invalid

INTRO_TEXT: str = "間違えやすい語の正しい表記を並べる。文字起こしへの指示としては効かない。"
"""まとまりの見出しの下に出す、並べるものと、指示としては効かないことの説明。"""

NOTES_TEXT: str = (
    "・ヒントを渡すと、句読点が付く・改行がまとまる・口癖が一部消える。\n"
    "・並べた表記にほかの語が引っ張られたら、その語も追加する"
    "（例: TypeScript がタイプスクリプトになったら「TypeScript」を追加する）。"
)
"""まとまりの末尾に出す、ヒントを渡すと変わる書き方と、引っ張られた語への対処。"""

EMPTY_PRESETS_TEXT: str = (
    "ヒントのプリセットはまだありません。無い間は、ヒントを渡さずに文字を起こします。"
)
"""プリセットが 1 件も無いときの案内。"""

EMPTY_WORDS_TEXT: str = "このプリセットにはまだ語がありません。"
"""語が 1 つも無いプリセットの、語の欄の代わりに出す文。"""

LIST_ACCESSIBLE_NAME: str = "表記のヒントのプリセット（上から順に語をつなぐ）"
"""プリセットの一覧の読み上げの名前。"""

NAME_PLACEHOLDER: str = "例: 開発"
"""プリセットの名前の欄のプレースホルダ。"""

UNNAMED_TEXT: str = "（名前未入力）"
"""名前が空のプリセットを、まとまりの頭に出す表示。"""

NAME_DISPLAY_MAX_CHARS: int = 20
"""まとまりの頭に出す名前の長さの上限（超えたら末尾を省く）。"""

DIMMED_OPACITY: float = 0.4
"""無効のプリセットの語の欄を薄くする濃さ。"""

WORD_PAIR_MIN_WIDTH_PX: int = 240
"""語の欄と削除ボタンの組 1 つに要る幅。部品の幅が組 2 つ分に足りなければ 1 列に積む。"""

WORD_COLUMNS_WIDE: int = 2
WORD_COLUMNS_NARROW: int = 1
"""語の組を並べる列の数（幅があるとき・狭いとき）。"""

ENABLED_TEXT: str = "有効"
DISABLED_TEXT: str = "無効"
"""有効の切り替えの右に出す、今の状態の文字。"""

LOCATION_NAME_LENGTH: int = 2
"""失敗の場所（添字, "name"）の長さ。"""

LOCATION_WORD_LENGTH: int = 3
"""失敗の場所（添字, "words", 語の添字）の長さ。"""


@dataclass
class _WordsView:
    """join_hint_words に渡す、欄の今の値（確かめを通らない値もそのまま持つ）。"""

    enabled: bool
    words: list[str]


@dataclass
class _WordCell:
    """語 1 つの欄・削除ボタン・欄の下のエラーの文。"""

    container: QWidget
    edit: QLineEdit
    error_label: QLabel


@dataclass(eq=False)
class _HintRow:
    """プリセット 1 件の欄の部品と、欄の下のエラーの文。"""

    container: QFrame
    enabled_box: QCheckBox
    size_label: QLabel
    name_edit: QLineEdit
    name_error_label: QLabel
    words_grid: QGridLayout
    cells: list[_WordCell] = field(default_factory=list)


def _display_name(name: str) -> str:
    """まとまりの頭に出す名前（前後の空白を除き、空なら「（名前未入力）」、長ければ末尾を省く）を返す。"""
    shown = name.strip() or UNNAMED_TEXT
    if len(shown) <= NAME_DISPLAY_MAX_CHARS:
        return shown
    return shown[: NAME_DISPLAY_MAX_CHARS - 1] + "…"


def _spoken_name(position: int, name: str) -> str:
    """読み上げの名前に使うプリセットの呼び方（名前が空なら一覧の何件目か）を返す。"""
    return name.strip() or f"プリセット {position + 1} 件目"


def _byte_length(words: _WordsView) -> int:
    """語をつないだ手がかりの UTF-8 のバイト数を返す（有効かどうかは見ない）。"""
    return len(join_hint_words([words]).encode("utf-8"))


def _stripped_words(texts: Sequence[str]) -> list[str]:
    """欄の文字から前後の空白を除く（保存の確かめと同じ数え方にそろえる）。"""
    return [text.strip() for text in texts]


def _repolish(widget: QWidget) -> None:
    """property を変えた部品にスタイルシートを当て直す。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _dim(widget: QWidget, *, dimmed: bool) -> None:
    """部品を薄くする・戻す。"""
    if dimmed:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(DIMMED_OPACITY)
        widget.setGraphicsEffect(effect)
    else:
        widget.setGraphicsEffect(None)


class HintPresetPanel(QWidget):
    """設定画面の「表記のヒント」のまとまりに置く、有効なヒントの長さ・プリセットの縦の並び・「プリセットを追加」・補足。

    追加・削除・並べ替え・入力はこの部品の中だけを変え、settings.yaml へは設定画面の保存で書く。
    """

    changed = Signal()
    """追加・削除・並べ替え・切り替え・欄の入力で値が変わった（設定画面が変えた欄の数えに使う）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """空の一覧で部品を作る。"""
        super().__init__(parent)
        self._rows: list[_HintRow] = []
        # プリセットを追う番号: 一覧の並びと同じ順に持つ。開いたとき・保存したときの分は 0 から振り、追加した分はそれより大きい番号にする
        self._ids: list[int] = []
        self._baseline_count = 0
        self._next_id = 0
        self._columns = WORD_COLUMNS_WIDE
        self.setObjectName("hint_preset_panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("表記のヒント")
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        intro = QLabel(INTRO_TEXT)
        intro.setObjectName("hint_intro")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # 有効なヒントの長さ: 見出しと「{長さ} / 上限 バイト」の文字、その下にバー
        self._length_row = QWidget()
        self._length_row.setObjectName("hint_length")
        self._length_row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        length_column = QVBoxLayout(self._length_row)
        length_column.setContentsMargins(0, 0, 0, 0)
        length_head = QHBoxLayout()
        length_title = QLabel("有効なヒントの長さ")
        length_title.setProperty("role", "heading")
        self._length_text = QLabel()
        length_head.addWidget(length_title)
        length_head.addStretch(1)
        length_head.addWidget(self._length_text)
        length_column.addLayout(length_head)
        self._length_bar = QProgressBar()
        self._length_bar.setRange(0, HINT_MAX_BYTES)
        self._length_bar.setTextVisible(False)
        length_column.addWidget(self._length_bar)
        outer.addWidget(self._length_row)
        self._length_error = QLabel()
        self._length_error.setObjectName("hint_length_error")
        self._length_error.setTextFormat(Qt.TextFormat.PlainText)
        self._length_error.setProperty("role", "error")
        self._length_error.setWordWrap(True)
        self._length_error.hide()
        outer.addWidget(self._length_error)

        self._empty_label = QLabel(EMPTY_PRESETS_TEXT)
        self._empty_label.setObjectName("hint_preset_empty")
        self._empty_label.setWordWrap(True)
        outer.addWidget(self._empty_label)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(8)
        outer.addLayout(self._rows_layout)

        add_button = QPushButton("プリセットを追加")
        add_button.setObjectName("hint_preset_add")
        add_button.clicked.connect(self.add_preset)
        outer.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)

        notes = QLabel(NOTES_TEXT)
        notes.setObjectName("hint_notes")
        notes.setProperty("role", "muted")
        notes.setWordWrap(True)
        outer.addWidget(notes)

        self._refresh_length()

    # --- 値の出し入れ ---

    def set_presets(self, presets: Sequence[HintPresetSettings]) -> None:
        """渡したプリセットで一覧を作り直し、長さを数え直す。空なら空の案内を出す。"""
        self._rebuild([preset.model_dump() for preset in presets], self._number_saved(len(presets)))

    def collect(self) -> list[dict[str, Any]]:
        """今の並びのプリセットを 設定と同じ構造の dict（name・words・enabled）の並びにする。空の語の欄もそのまま入れる。"""
        return [
            {
                "name": row.name_edit.text(),
                "words": [cell.edit.text() for cell in row.cells],
                "enabled": row.enabled_box.isChecked(),
            }
            for row in self._rows
        ]

    def add_preset(self) -> None:
        """末尾に名前と語が空で有効のプリセットを追加し、名前の欄へフォーカスを移して changed を emit する。"""
        values = self.collect()
        values.append({"name": "", "words": [], "enabled": True})
        # 追加したプリセットには、振ったどの番号より大きい番号を振る
        added_id = self._next_id
        self._next_id += 1
        self._rebuild(values, [*self._ids, added_id])
        self._rows[-1].name_edit.setFocus()
        self.changed.emit()

    def add_word(self, position: int) -> None:
        """一覧の何件目のプリセットの語の末尾に空の欄を追加してフォーカスを移し、changed を emit する。"""
        values = self.collect()
        values[position]["words"].append("")
        self._rebuild(values, self._ids)
        self._rows[position].cells[-1].edit.setFocus()
        self.changed.emit()

    def hint_length(self) -> int:
        """今の欄の値で、有効なプリセットの語をつないだ UTF-8 のバイト数を返す。"""
        views = [
            _WordsView(
                enabled=row.enabled_box.isChecked(),
                words=_stripped_words([cell.edit.text() for cell in row.cells]),
            )
            for row in self._rows
        ]
        return len(join_hint_words(views).encode("utf-8"))

    def change_values(self) -> dict[str, object]:
        """変えた欄の数えに使う値を、プリセット 1 つ = 1 キーと、並べ替えの 1 キーで返す。"""
        values: dict[str, object] = {
            f"hint_presets[{preset_id}]": (preset["name"], preset["words"], preset["enabled"])
            for preset_id, preset in zip(self._ids, self.collect(), strict=True)
        }
        # 開いたとき・保存したときからあって今も残っているプリセットだけで、番号の小さい順に並んでいるか（追加したプリセットは見ない）
        kept = [preset_id for preset_id in self._ids if preset_id < self._baseline_count]
        values["hint_presets.order"] = kept == sorted(kept)
        return values

    def mark_saved(self) -> None:
        """プリセットの番号を、今の並びの順に 0 から振り直す（追加したプリセットも保存したプリセットとして扱う）。保存が書けた後に呼ぶ。"""
        self._ids = self._number_saved(len(self._rows))

    def focus_field(self, location: tuple[int | str, ...]) -> None:
        """失敗の場所（hint_presets より後ろ）で欄を探し、フォーカスを移す。場所が空なら長さの行へ移す。"""
        # 場所が hint_presets だけ: 長さの行
        if not location:
            self._length_row.setFocus()
            return
        widget = self._widget_at(location)
        if widget is not None:
            widget.setFocus()

    # --- エラーの表示 ---

    def show_error(self, location: tuple[int | str, ...], message: str) -> None:
        """失敗の場所の欄の下にエラーを出し、欄を赤くする（同じ欄の失敗は重ねて出す）。場所が空なら長さの行の下に出す。"""
        # 場所が hint_presets だけ: 長さの行の下
        if not location:
            self._append_error(self._length_error, message)
            return
        widget = self._widget_at(location)
        label = self._error_label_at(location)
        if widget is None or label is None:
            return
        self._append_error(label, message)
        set_invalid(widget, invalid=True)

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て削除する。"""
        self._length_error.clear()
        self._length_error.hide()
        for row in self._rows:
            row.name_error_label.clear()
            row.name_error_label.hide()
            set_invalid(row.name_edit, invalid=False)
            for cell in row.cells:
                cell.error_label.clear()
                cell.error_label.hide()
                set_invalid(cell.edit, invalid=False)

    @staticmethod
    def _append_error(label: QLabel, message: str) -> None:
        """エラーの文を出す（既にあれば改行して重ねる）。"""
        label.setText(f"{label.text()}\n{message}" if label.text() else message)
        label.show()

    def _widget_at(self, location: tuple[int | str, ...]) -> QWidget | None:
        """失敗の場所（（何件目か, "name"）か（何件目か, "words", 何つ目か））の欄を返す。無ければ None。"""
        position = location[0]
        if not isinstance(position, int) or not 0 <= position < len(self._rows):
            return None
        row = self._rows[position]
        if len(location) == LOCATION_NAME_LENGTH and location[1] == "name":
            return row.name_edit
        if len(location) == LOCATION_WORD_LENGTH and location[1] == "words":
            word = location[2]
            if isinstance(word, int) and 0 <= word < len(row.cells):
                return row.cells[word].edit
        return None

    def _error_label_at(self, location: tuple[int | str, ...]) -> QLabel | None:
        """失敗の場所の欄の下のエラーの文を返す。無ければ None。"""
        position = location[0]
        if not isinstance(position, int) or not 0 <= position < len(self._rows):
            return None
        row = self._rows[position]
        if len(location) == LOCATION_NAME_LENGTH:
            return row.name_error_label
        word = location[2]
        if isinstance(word, int) and 0 <= word < len(row.cells):
            return row.cells[word].error_label
        return None

    # --- 組み立て ---

    def _number_saved(self, count: int) -> list[int]:
        """保存した件数のプリセットに 0 から番号を振り直し（追加する番号はその次から）、その番号の並びを返す。"""
        self._baseline_count = count
        self._next_id = count
        return list(range(count))

    def _rebuild(self, values: list[dict[str, Any]], ids: list[int]) -> None:
        """プリセットの値の並びと番号の並びで、まとまりを全て作り直し、長さを数え直す。"""
        self._ids = ids
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        for position, value in enumerate(values):
            self._add_row(position, value, last=position == len(values) - 1)
        self._empty_label.setVisible(not values)
        self._refresh_length()

    def _move(self, position: int, offset: int) -> None:
        """プリセットを offset だけ動かす。"""
        values = self.collect()
        target = position + offset
        values[position], values[target] = values[target], values[position]
        ids = list(self._ids)
        ids[position], ids[target] = ids[target], ids[position]
        self._rebuild(values, ids)
        self.changed.emit()

    def _remove(self, position: int) -> None:
        """プリセットを一覧から削除する。"""
        values = self.collect()
        del values[position]
        ids = list(self._ids)
        del ids[position]
        self._rebuild(values, ids)
        self.changed.emit()

    def _remove_word(self, position: int, word: int) -> None:
        """プリセットの語を 1 つ削除する。"""
        values = self.collect()
        del values[position]["words"][word]
        self._rebuild(values, self._ids)
        self.changed.emit()

    def _on_input(self) -> None:
        """欄の入力・切り替えで、長さと薄く見せる語の欄を更新し、changed を emit する。"""
        self._refresh_length()
        self.changed.emit()

    def _add_row(self, position: int, value: dict[str, Any], *, last: bool) -> None:
        """プリセット 1 件のまとまり（頭に有効・名前・語の数と長さ・上へ・下へ・削除、下に名前の欄と語の欄）を追加する。"""
        frame = QFrame()
        frame.setProperty("role", "surface")
        column = QVBoxLayout(frame)

        # 頭: 有効の切り替えと今の状態の文字・入れた名前の表示・語の数と長さ・上へ・下へ・削除
        head = QHBoxLayout()
        enabled_box = QCheckBox(ENABLED_TEXT if value["enabled"] else DISABLED_TEXT)
        enabled_box.setObjectName(f"hint_preset_enabled_{position}")
        enabled_box.setChecked(bool(value["enabled"]))
        heading = QLabel()
        heading.setProperty("role", "heading")
        size_label = QLabel()
        size_label.setObjectName(f"hint_preset_size_{position}")
        size_label.setProperty("role", "muted")
        up_button = self._operation_button("↑", f"hint_preset_up_{position}")
        up_button.setEnabled(position > 0)
        up_button.clicked.connect(lambda: self._move(position, -1))
        down_button = self._operation_button("↓", f"hint_preset_down_{position}")
        down_button.setEnabled(not last)
        down_button.clicked.connect(lambda: self._move(position, 1))
        remove_button = self._operation_button("×", f"hint_preset_remove_{position}")
        remove_button.clicked.connect(lambda: self._remove(position))
        head.addWidget(enabled_box)
        head.addWidget(heading, 1)
        head.addWidget(size_label)
        for button in (up_button, down_button, remove_button):
            head.addWidget(button)
        column.addLayout(head)

        # 名前の欄
        name_title = QLabel("名前")
        name_title.setProperty("role", "heading")
        name_edit = QLineEdit(str(value["name"]))
        name_edit.setObjectName(f"hint_preset_name_{position}")
        name_edit.setPlaceholderText(NAME_PLACEHOLDER)
        name_title.setBuddy(name_edit)
        column.addWidget(name_title)
        column.addWidget(name_edit)
        name_error_label = self._error_label()
        column.addWidget(name_error_label)

        # 語の欄: 入力と削除ボタンの組を格子に並べる。語が無ければ代わりの文を出す
        words_title = QLabel("語")
        words_title.setProperty("role", "heading")
        column.addWidget(words_title)
        words: list[str] = [str(word) for word in value["words"]]
        words_grid = QGridLayout()
        row = _HintRow(frame, enabled_box, size_label, name_edit, name_error_label, words_grid)
        for word_position, word in enumerate(words):
            row.cells.append(self._make_word_cell(position, word_position, word))
        if words:
            column.addLayout(words_grid)
        else:
            empty_words = QLabel(EMPTY_WORDS_TEXT)
            empty_words.setObjectName(f"hint_words_empty_{position}")
            column.addWidget(empty_words)
        add_word_button = QPushButton("語を追加")
        add_word_button.setObjectName(f"hint_word_add_{position}")
        add_word_button.clicked.connect(lambda: self.add_word(position))
        column.addWidget(add_word_button, alignment=Qt.AlignmentFlag.AlignLeft)

        def sync_names() -> None:
            """入れた名前で、頭の表示と、操作の読み上げの名前を合わせる（空なら何件目か）。"""
            current = name_edit.text()
            spoken = _spoken_name(position, current)
            heading.setText(_display_name(current))
            enabled_box.setAccessibleName(f"{spoken}を有効にする")
            up_button.setAccessibleName(f"{spoken}を上へ")
            down_button.setAccessibleName(f"{spoken}を下へ")
            remove_button.setAccessibleName(f"{spoken}を削除")

        def sync_enabled() -> None:
            """有効の切り替えの右の文字と、語の欄の薄さ・取り消し線を今の状態に合わせる。"""
            enabled = enabled_box.isChecked()
            enabled_box.setText(ENABLED_TEXT if enabled else DISABLED_TEXT)
            for cell in row.cells:
                font = cell.edit.font()
                font.setStrikeOut(not enabled)
                cell.edit.setFont(font)
                _dim(cell.edit, dimmed=not enabled)

        name_edit.textChanged.connect(lambda _text: (sync_names(), self._on_input()))
        enabled_box.toggled.connect(lambda _checked: (sync_enabled(), self._on_input()))
        for cell in row.cells:
            cell.edit.textChanged.connect(lambda _text: self._on_input())
        sync_names()
        sync_enabled()

        self._rows.append(row)
        self._rows_layout.addWidget(frame)
        self._arrange_words(row)
        # 表示中の部品に追加した部品は次のイベントの処理まで出ないため、すぐ出す
        frame.show()

    def _make_word_cell(self, position: int, word_position: int, word: str) -> _WordCell:
        """語 1 つの欄・削除ボタン・欄の下のエラーの文を作る。"""
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        pair = QHBoxLayout()
        edit = QLineEdit(word)
        edit.setObjectName(f"hint_word_{position}_{word_position}")
        edit.setAccessibleName(f"{word_position + 1} つ目の語")
        remove_button = self._operation_button("×", f"hint_word_remove_{position}_{word_position}")
        remove_button.setAccessibleName(f"{word_position + 1} つ目の語を削除")
        remove_button.clicked.connect(lambda: self._remove_word(position, word_position))
        pair.addWidget(edit, 1)
        pair.addWidget(remove_button)
        column.addLayout(pair)
        error_label = self._error_label()
        column.addWidget(error_label)
        return _WordCell(container, edit, error_label)

    def _arrange_words(self, row: _HintRow) -> None:
        """語の組を、今の列の数で格子に並べる（左から右、上から下が語の順）。"""
        for cell in row.cells:
            row.words_grid.removeWidget(cell.container)
        for index, cell in enumerate(row.cells):
            row.words_grid.addWidget(cell.container, index // self._columns, index % self._columns)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 Qt の名前
        """幅が組 2 つ分に足りなければ語を 1 列に積み、足りていれば 2 列に戻す。"""
        super().resizeEvent(event)
        columns = (
            WORD_COLUMNS_WIDE
            if event.size().width() >= WORD_PAIR_MIN_WIDTH_PX * WORD_COLUMNS_WIDE
            else WORD_COLUMNS_NARROW
        )
        if columns != self._columns:
            self._columns = columns
            for row in self._rows:
                self._arrange_words(row)

    def _refresh_length(self) -> None:
        """有効なヒントの長さ（バー・文字）と、プリセットごとの語の数と長さを数え直す。"""
        length = self.hint_length()
        over = length > HINT_MAX_BYTES
        text = f"{length} / {HINT_MAX_BYTES} バイト"
        if over:
            text += f"（{length - HINT_MAX_BYTES} バイト超過）"
        self._length_text.setText(text)
        self._length_text.setProperty("role", "error" if over else "")
        _repolish(self._length_text)
        self._length_bar.setValue(min(length, HINT_MAX_BYTES))
        self._length_bar.setProperty("over", over)
        _repolish(self._length_bar)
        # プリセットごとの語の数と、その語だけをつないだ長さ（無効のプリセットも出す）
        for row in self._rows:
            words = _stripped_words([cell.edit.text() for cell in row.cells])
            size = _byte_length(_WordsView(enabled=True, words=words))
            row.size_label.setText(f"{len(words)} 語・{size} バイト")

    @staticmethod
    def _operation_button(text: str, object_name: str) -> QPushButton:
        """上へ・下へ・削除のボタンを作る（見た目はマーカー。読み上げの名前は呼ぶ側が付ける）。"""
        button = QPushButton(text)
        button.setObjectName(object_name)
        return button

    @staticmethod
    def _error_label() -> QLabel:
        """欄の下に出すエラーの文（初めは隠す）を作る。"""
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setProperty("role", "error")
        label.setWordWrap(True)
        label.hide()
        return label
