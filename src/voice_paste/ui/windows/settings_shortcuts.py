"""設定画面の「ショートカット」のまとまりに配置する、用語集のプリセットを切り替えるショートカットの一覧。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.os_kind import OsKind
from voice_paste.shared.settings import GlossaryPresetHotkeySettings
from voice_paste.ui.windows.settings_fields import set_invalid

SHORTCUT_DEFAULT_HOTKEYS: dict[OsKind, str] = {
    OsKind.WINDOWS: "<ctrl>+<alt>+s",
    OsKind.LINUX: "<cmd>+<alt>+g",
}
"""OS の種類ごとの、追加した行のキーの初期値（pynput の書式）。GNOME は Super+Alt+S を画面の読み上げの切り替えに割り当てている。"""

HEADING_TEXT: str = "用語集のプリセットを切り替える"
ADD_TEXT: str = "行追加"
EMPTY_TEXT: str = "ショートカットはありません。"
NOTE_TEXT: str = (
    "押すと、補正に使用する用語集のプリセットを切り替えます。ほかのホットキーと同じ組み合わせは登録できません。"
)
LIST_NAME: str = "用語集のプリセットを切り替えるショートカットの一覧"
"""見出し・行の追加ボタン・行が無いときの文・一覧の下の補助文・一覧の読み上げの名前。"""


@dataclass
class _Row:
    """ショートカット 1 行の今の値。"""

    row_id: int
    """行の番号（開いたとき・保存したときの何行目か。追加した行はその件数から続く番号）。変えた行の数えに使用する。"""
    hotkey: str
    preset: object
    """切り替える用語集のプリセットの識別子（GlossaryPanel の識別子。名前を変えても変わらない）。"""
    added: bool
    """追加してまだ保存していない行か（背景を変えて示す）。"""


class ShortcutPanel(QWidget):
    """見出しの行（見出しと行の追加ボタン）と、ショートカットの一覧（キーの欄・切り替える用語集のプリセットの選択・削除ボタン）。"""

    changed = Signal()
    """行の追加・削除、キーの入力、プリセットの選択で値が変わった（設定画面が変えた欄の数えに使用する）。"""

    capturing = Signal(bool)
    """キーの欄が入力待ちに入った（True）・出た（False）。"""

    def __init__(
        self,
        os_kind: OsKind,
        other_hotkeys: Callable[[], Sequence[str]],
        parent: QWidget | None = None,
    ) -> None:
        """OS の種類（追加した行のキーの初期値を決める）と、受け付けているほかのホットキーを返却する関数を受けて、空の一覧を作る。"""
        super().__init__(parent)
        self._os_kind = os_kind
        self._other_hotkeys = other_hotkeys
        self._presets: list[tuple[object, str]] = []
        self._active: object = None
        self._rows: list[_Row] = []
        self._baseline: dict[int, tuple[str, object]] = {}
        self._next_id = 0
        self._hotkey_edits: list[QWidget] = []
        self._preset_combos: list[QComboBox] = []
        self._errors: dict[tuple[int, str], list[str]] = {}
        """欄の下に出すエラー（何行目か・hotkey か preset → 文言）。行を作り直しても残す。"""
        self.setObjectName("shortcut_panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 見出しの行: 見出しと、右に行の追加ボタン
        head = QWidget()
        head.setObjectName("shortcut_head")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(HEADING_TEXT)
        heading.setProperty("role", "heading")
        add_button = QPushButton(ADD_TEXT)
        add_button.setObjectName("add_shortcut_button")
        add_button.clicked.connect(self.add_row)
        head_layout.addWidget(heading, 1)
        head_layout.addWidget(add_button)
        outer.addWidget(head)

        self._empty_label = QLabel(EMPTY_TEXT)
        self._empty_label.setObjectName("shortcut_empty")
        outer.addWidget(self._empty_label)

        self._list = QFrame()
        self._list.setObjectName("shortcut_list")
        self._list.setAccessibleName(LIST_NAME)
        self._rows_layout = QVBoxLayout(self._list)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._list)

        note = QLabel(NOTE_TEXT)
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        self._rebuild()

    # --- 値の出し入れ ---

    def set_rows(self, rows: Sequence[GlossaryPresetHotkeySettings]) -> None:
        """設定の行で一覧を作り直し、開いたときの行として記録する。一覧に無い名前のプリセットを指す行は入れない。"""
        ident_by_name = {name: ident for ident, name in self._presets}
        self._rows = [
            _Row(row_id=0, hotkey=row.hotkey, preset=ident_by_name[row.preset], added=False)
            for row in rows
            if row.preset in ident_by_name
        ]
        self._number_saved()
        self._rebuild()

    def set_presets(self, presets: Sequence[tuple[object, str]], active: object) -> None:
        """選択欄の選択肢を今のプリセットの一覧に替え、一覧に無いプリセットを指す行を削除する。補正に使用するプリセットを行の追加の初期値にする。"""
        self._presets = list(presets)
        self._active = active
        idents = {ident for ident, _name in self._presets}
        kept = [row for row in self._rows if row.preset in idents]
        removed = len(kept) != len(self._rows)
        self._rows = kept
        # 行が減ると何行目かがずれるため、出していたエラーを削除する
        if removed:
            self._errors.clear()
        self._rebuild()
        # プリセットを削除して行が減った: 値が変わったことを通知する
        if removed:
            self.changed.emit()

    def add_row(self) -> None:
        """末尾に初期値の行を追加してキーの欄へフォーカスを移す。キーはほかのホットキーかほかの行が使用していれば空にする。"""
        default = SHORTCUT_DEFAULT_HOTKEYS[self._os_kind]
        used = {hotkey.lower() for hotkey in self._other_hotkeys()} | {
            row.hotkey.lower() for row in self._rows
        }
        hotkey = "" if default.lower() in used else default
        self._rows.append(_Row(row_id=self._next_id, hotkey=hotkey, preset=self._active, added=True))
        self._next_id += 1
        self._rebuild()
        self._hotkey_edits[-1].setFocus()
        self.changed.emit()

    def collect(self) -> list[dict[str, str]]:
        """行を、設定の glossary_preset_hotkeys と同じ構造の dict（hotkey・そのときのプリセットの名前）の並びにする。"""
        name_by_ident = dict(self._presets)
        return [{"hotkey": row.hotkey, "preset": name_by_ident[row.preset]} for row in self._rows]

    def change_count(self) -> int:
        """開いたとき・保存したときの行から、追加・削除・キーかプリセットを変えた行を 1 件ずつ数える。"""
        current = {row.row_id: (row.hotkey, row.preset) for row in self._rows}
        ids = current.keys() | self._baseline.keys()
        return sum(1 for row_id in ids if current.get(row_id) != self._baseline.get(row_id))

    def mark_saved(self) -> None:
        """今の行を開いたときの行として記録し直し、追加した行の背景を戻す。"""
        for row in self._rows:
            row.added = False
        self._number_saved()
        self._rebuild()

    def focus_field(self, index: int, field: str) -> None:
        """何行目かのキーの欄（hotkey）かプリセットの選択欄（preset）へフォーカスを移す。"""
        if not 0 <= index < len(self._rows):
            return
        widget = self._hotkey_edits[index] if field == "hotkey" else self._preset_combos[index]
        widget.setFocus()

    def show_error(self, index: int, field: str, message: str) -> None:
        """何行目かのキーの欄（hotkey）かプリセットの選択欄（preset）の下にエラーを出す（同じ欄の失敗は重ねて出す）。"""
        self._errors.setdefault((index, field), []).append(message)
        self._rebuild()

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て削除する。"""
        if self._errors:
            self._errors.clear()
            self._rebuild()

    # --- 組み立て ---

    def _number_saved(self) -> None:
        """行に 0 から番号を振り直して開いたときの行として記録する（追加する番号はその次から）。"""
        for row_id, row in enumerate(self._rows):
            row.row_id = row_id
        self._baseline = {row.row_id: (row.hotkey, row.preset) for row in self._rows}
        self._next_id = len(self._rows)

    def _rebuild(self) -> None:
        """行の値で一覧の部品を全て作り直す。行が無ければ一覧の代わりに行が無いときの文を出す。"""
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._hotkey_edits = []
        self._preset_combos = []
        for index, row in enumerate(self._rows):
            self._rows_layout.addWidget(self._build_row(index, row))
        self._empty_label.setVisible(not self._rows)
        self._list.setVisible(bool(self._rows))

    def _build_row(self, index: int, row: _Row) -> QFrame:
        """1 行（キーの欄・切り替える用語集のプリセットの選択・削除ボタン）を作る。"""
        # 設定画面と相互に import するため、ホットキーの欄はここで参照する
        from voice_paste.ui.windows.settings_window import HotkeyEdit

        number = index + 1
        frame = QFrame()
        frame.setObjectName(f"shortcut_row_{index}")
        frame.setProperty("role", "shortcut_row")
        frame.setProperty("added", row.added)
        column = QVBoxLayout(frame)
        line = QHBoxLayout()
        column.addLayout(line)

        hotkey_edit = HotkeyEdit(row.hotkey)
        hotkey_edit.setObjectName(f"shortcut_hotkey_{index}")
        hotkey_edit.setAccessibleName(f"{number} 行目のキーの組み合わせ")
        hotkey_edit.capturing.connect(self.capturing)
        hotkey_edit.textChanged.connect(lambda _text: self._on_hotkey(row, hotkey_edit.hotkey))

        combo = QComboBox()
        combo.setObjectName(f"shortcut_preset_{index}")
        combo.setAccessibleName(f"{number} 行目の切り替える用語集のプリセット")
        for ident, name in self._presets:
            combo.addItem(name, ident)
        combo.setCurrentIndex(combo.findData(row.preset))
        combo.currentIndexChanged.connect(lambda position: self._on_preset(row, combo, position))

        remove_button = QPushButton("×")
        remove_button.setObjectName(f"shortcut_remove_{index}")
        remove_button.setAccessibleName(f"{number} 行目を削除")
        remove_button.setToolTip(f"{number} 行目を削除")
        remove_button.clicked.connect(lambda: self._remove(row))

        line.addWidget(hotkey_edit, 1)
        line.addWidget(combo, 1)
        line.addWidget(remove_button, alignment=Qt.AlignmentFlag.AlignRight)
        # 保存で確認に通らなかった欄: 欄を赤くし、行の下にエラーを出す
        for field, widget in (("hotkey", hotkey_edit), ("preset", combo)):
            messages = self._errors.get((index, field))
            if not messages:
                continue
            set_invalid(widget, invalid=True)
            error_label = QLabel("\n".join(messages))
            error_label.setObjectName(f"shortcut_error_{field}_{index}")
            error_label.setTextFormat(Qt.TextFormat.PlainText)
            error_label.setProperty("role", "error")
            error_label.setWordWrap(True)
            column.addWidget(error_label)
        self._hotkey_edits.append(hotkey_edit)
        self._preset_combos.append(combo)
        return frame

    # --- 操作 ---

    def _on_hotkey(self, row: _Row, hotkey: str) -> None:
        """キーの欄に入った組み合わせを行に入れる。"""
        row.hotkey = hotkey
        self.changed.emit()

    def _on_preset(self, row: _Row, combo: QComboBox, position: int) -> None:
        """選んだプリセットの識別子を行に入れる。"""
        if position < 0:
            return
        row.preset = combo.itemData(position)
        self.changed.emit()

    def _remove(self, row: _Row) -> None:
        """行を一覧から削除する。"""
        self._rows.remove(row)
        self._errors.clear()
        self._rebuild()
        self.changed.emit()
