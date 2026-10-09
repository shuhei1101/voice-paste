"""設定画面の種類ごとのタブに置く、カスタムプリセットの一覧。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.settings import BrowserPreset, EndpointPreset, Preset
from voice_paste.ui.windows.settings_fields import connect_changed

PRESET_MODELS: dict[str, type[BrowserPreset] | type[EndpointPreset]] = {
    "browser": BrowserPreset,
    "endpoint": EndpointPreset,
}
"""プリセットの種類ごとの設定のモデル（種類ごとに違う欄をここから組み立てる）。"""

COMMON_ATTRIBUTES: tuple[str, ...] = ("kind", "title", "url", "hotkey", "enabled")
"""どの種類のプリセットも持つ項目（種類ごとに違う欄はこれ以外の項目）。"""

PRESET_FIELD_LABELS: dict[str, str] = {
    "enabled": "有効の切り替え",
    "title": "タイトル",
    "url": "URL",
    "hotkey": "確定のホットキー",
    "send_enter": "Enter まで送る",
    "authorization": "Authorization",
}
"""プリセットの項目ごとの、画面の欄の名前（エラーの一覧にも出す）。"""

TITLE_PLACEHOLDER: str = "録音の画面のボタンに出す名前"
"""タイトルの欄のプレースホルダ。"""

UNTITLED_TEXT: str = "（タイトル未入力）"
"""タイトルが空のときに、まとまりの頭に出す表示。"""

ENABLED_TEXT: str = "有効"
DISABLED_TEXT: str = "無効"
"""有効の切り替えの右に出す、今の状態の文字。"""


def _preset_name(position: int, title: str) -> str:
    """読み上げとエラーの一覧に使うプリセットの呼び方（タイトルが空ならそのタブの中の何件目か）。"""
    return title or f"プリセット {position + 1} 件目"


class _PresetRow:
    """プリセット 1 件の欄の部品と、欄の下のエラーの文。"""

    def __init__(self, container: QWidget, widgets: dict[str, QWidget]) -> None:
        self.container = container
        self.widgets = widgets
        self.error_labels: dict[str, QLabel] = {}


class PresetListPanel(QWidget):
    """設定画面の 1 つの種類のタブに置く、プリセットのまとまりの縦の並びと「プリセットを足す」。"""

    changed = Signal()
    """足す・消す・並べ替え・欄の入力で値が変わった（設定画面が変えた欄の数えに使う）。"""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        """この一覧が受け持つプリセットの種類で、空の一覧を作る。"""
        super().__init__(parent)
        # 設定画面と相互に import するため、種類の名前はここで引く
        from voice_paste.ui.windows.settings_window import PRESET_KIND_NAMES

        self.kind = kind
        self._model = PRESET_MODELS[kind]
        self._rows: list[_PresetRow] = []
        self.setObjectName(f"preset_list_{kind}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("カスタムプリセット")
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        self._empty_label = QLabel(
            f"{PRESET_KIND_NAMES[kind]}のプリセットはまだありません。"
            "足すと、録音の画面の「カスタムプリセット」にボタンが出ます。"
        )
        self._empty_label.setObjectName(f"preset_empty_{kind}")
        self._empty_label.setWordWrap(True)
        outer.addWidget(self._empty_label)

        self._rows_layout = QVBoxLayout()
        outer.addLayout(self._rows_layout)

        add_button = QPushButton("プリセットを足す")
        add_button.setObjectName(f"add_preset_button_{kind}")
        add_button.clicked.connect(self.add_preset)
        outer.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)

    # --- 値の出し入れ ---

    def set_presets(self, presets: Sequence[Preset]) -> None:
        """渡したプリセット（この種類のものだけ）で一覧を作り直す。空なら空の案内を出す。"""
        self._rebuild([preset.model_dump() for preset in presets])

    def collect(self) -> list[dict[str, Any]]:
        """今の並びのプリセットを、settings.toml と同じ形の dict の並びにする（kind を含める）。"""
        collected: list[dict[str, Any]] = []
        for row in self._rows:
            widgets = row.widgets
            item: dict[str, Any] = {
                "kind": self.kind,
                "enabled": _checked(widgets["enabled"]),
                "title": _text(widgets["title"]),
                "url": _text(widgets["url"]),
                "hotkey": _hotkey(widgets["hotkey"]),
            }
            # 種類ごとに違う欄（真偽値はチェックボックス、文字は伏せ字の欄）
            for attribute in self._extra_attributes():
                widget = widgets[attribute]
                item[attribute] = _checked(widget) if isinstance(widget, QCheckBox) else _text(widget)
            collected.append(item)
        return collected

    def add_preset(self) -> None:
        """末尾に空のプリセット（有効。ブラウザ添付は Enter まで送るがオン）を足し、タイトルの欄へフォーカスを移して changed を emit する。"""
        values = self.collect()
        values.append(self._empty_preset())
        self._rebuild(values)
        self._rows[-1].widgets["title"].setFocus()
        self.changed.emit()

    def focus_field(self, position: int, field: str) -> None:
        """この一覧の中の何件目かと項目の名前で欄を探し、フォーカスを移す。"""
        if 0 <= position < len(self._rows) and field in self._rows[position].widgets:
            self._rows[position].widgets[field].setFocus()

    # --- エラーの表示 ---

    def show_error(self, position: int, field: str, message: str) -> None:
        """何件目の項目の欄の下にエラーを出し、欄を赤くする（同じ欄の失敗は重ねて出す）。"""
        row = self._rows[position]
        widget = row.widgets[field]
        label = row.error_labels[field]
        label.setText(f"{label.text()}\n{message}" if label.text() else message)
        label.show()
        _set_invalid(widget, invalid=True)

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て消す。"""
        for row in self._rows:
            for field, label in row.error_labels.items():
                label.clear()
                label.hide()
                _set_invalid(row.widgets[field], invalid=False)

    # --- 組み立て ---

    def _extra_attributes(self) -> list[str]:
        """この種類のモデルの、どの種類も持つ項目でない項目（種類ごとに違う欄）の名前を並びのまま返す。"""
        return [name for name in self._model.model_fields if name not in COMMON_ATTRIBUTES]

    def _empty_preset(self) -> dict[str, Any]:
        """足すときの空のプリセット（有効。種類ごとに違う欄はモデルの既定）を dict で返す。"""
        return {
            "kind": self.kind,
            "enabled": True,
            "title": "",
            "url": "",
            "hotkey": "",
            **{
                attribute: self._model.model_fields[attribute].get_default()
                for attribute in self._extra_attributes()
            },
        }

    def _rebuild(self, values: list[dict[str, Any]]) -> None:
        """プリセットの値の並びで、まとまりを全て作り直す。"""
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

    def _move(self, position: int, offset: int) -> None:
        """プリセットを offset だけ動かす（同じ種類の中だけ）。"""
        values = self.collect()
        target = position + offset
        values[position], values[target] = values[target], values[position]
        self._rebuild(values)
        self.changed.emit()

    def _remove(self, position: int) -> None:
        """プリセットを一覧から消す。"""
        values = self.collect()
        del values[position]
        self._rebuild(values)
        self.changed.emit()

    def _add_row(self, position: int, value: dict[str, Any], *, last: bool) -> None:
        """プリセット 1 件のまとまり（頭に有効・タイトル・上へ・下へ・消す、下に URL・種類ごとの欄・確定のホットキー）を足す。"""
        # 設定画面と相互に import するため、ホットキーの欄はここで引く
        from voice_paste.ui.windows.settings_window import HotkeyEdit

        title = str(value["title"])
        frame = QFrame()
        frame.setProperty("role", "surface")
        column = QVBoxLayout(frame)

        # 頭: 有効の切り替えと今の状態の文字・入れたタイトルの表示・上へ・下へ・消す
        head = QHBoxLayout()
        enabled = QCheckBox(ENABLED_TEXT if value["enabled"] else DISABLED_TEXT)
        enabled.setChecked(bool(value["enabled"]))
        enabled.toggled.connect(
            lambda checked, box=enabled: box.setText(ENABLED_TEXT if checked else DISABLED_TEXT)
        )
        heading = QLabel()
        heading.setObjectName(f"preset_heading_{position}")
        heading.setProperty("role", "heading")
        up_button = self._operation_button("↑", "preset_up", position)
        up_button.setEnabled(position > 0)
        up_button.clicked.connect(lambda: self._move(position, -1))
        down_button = self._operation_button("↓", "preset_down", position)
        down_button.setEnabled(not last)
        down_button.clicked.connect(lambda: self._move(position, 1))
        remove_button = self._operation_button("×", "preset_remove", position)
        remove_button.clicked.connect(lambda: self._remove(position))
        head.addWidget(enabled)
        head.addWidget(heading, 1)
        for button in (up_button, down_button, remove_button):
            head.addWidget(button)
        column.addLayout(head)

        # 欄: タイトル・URL・種類ごとに違う欄・確定のホットキー（どれも名前を見せる）
        title_edit = QLineEdit(title)
        title_edit.setPlaceholderText(TITLE_PLACEHOLDER)
        widgets: dict[str, QWidget] = {"enabled": enabled, "title": title_edit}
        row = _PresetRow(frame, widgets)
        url_edit = QLineEdit(str(value["url"]))
        url_edit.setPlaceholderText("https://")
        widgets["url"] = url_edit
        for attribute in self._extra_attributes():
            widgets[attribute] = self._extra_widget(attribute, value[attribute])
        hotkey_edit = HotkeyEdit(str(value["hotkey"]))
        widgets["hotkey"] = hotkey_edit
        clear_button = QPushButton("空にする")
        clear_button.setObjectName(f"preset_hotkey_clear_{position}")
        clear_button.clicked.connect(hotkey_edit.clear_hotkey)

        self._add_field(column, row, "title", title_edit, ())
        for attribute in ("url", *self._extra_attributes(), "hotkey"):
            extras = (clear_button,) if attribute == "hotkey" else ()
            self._add_field(column, row, attribute, widgets[attribute], extras)

        def sync_names() -> None:
            """入れたタイトルで、頭の表示と、操作の読み上げの名前を合わせる（空なら何件目か）。"""
            current = title_edit.text().strip()
            name = _preset_name(position, current)
            heading.setText(current or UNTITLED_TEXT)
            enabled.setAccessibleName(f"{name}を有効にする")
            up_button.setAccessibleName(f"{name}を上へ")
            down_button.setAccessibleName(f"{name}を下へ")
            remove_button.setAccessibleName(f"{name}を消す")
            clear_button.setAccessibleName(f"{name}のホットキーを空にする")

        def sync_clear_button() -> None:
            """ホットキーの欄が空でないときだけ「空にする」を押せるようにする。"""
            clear_button.setEnabled(bool(hotkey_edit.hotkey))

        title_edit.textChanged.connect(lambda _text: sync_names())
        hotkey_edit.textChanged.connect(lambda _text: sync_clear_button())
        sync_names()
        sync_clear_button()

        for attribute, widget in widgets.items():
            widget.setObjectName(f"preset_{attribute}_{position}")
            connect_changed(widget, self.changed.emit)
        self._rows.append(row)
        self._rows_layout.addWidget(frame)

    @staticmethod
    def _operation_button(text: str, prefix: str, position: int) -> QPushButton:
        """上へ・下へ・消すのボタンを作る（見た目は印。読み上げの名前は入れたタイトルに合わせて付ける）。"""
        button = QPushButton(text)
        button.setObjectName(f"{prefix}_{position}")
        return button

    @staticmethod
    def _extra_widget(attribute: str, value: Any) -> QWidget:
        """種類ごとに違う項目の欄を、値の型から作る（真偽値はチェックボックス、文字は伏せ字の欄）。"""
        if isinstance(value, bool):
            check_box = QCheckBox(PRESET_FIELD_LABELS[attribute])
            check_box.setChecked(value)
            return check_box
        line = QLineEdit(str(value))
        line.setEchoMode(QLineEdit.EchoMode.Password)
        return line

    @staticmethod
    def _add_field(
        column: QVBoxLayout,
        row: _PresetRow,
        attribute: str,
        widget: QWidget,
        extras: tuple[QWidget, ...],
    ) -> None:
        """欄 1 つ（名前・部品・欄の下のエラー）をまとまりへ足す。"""
        # チェックボックスは名前を自分の文字に持つ
        if not isinstance(widget, QCheckBox):
            label = QLabel(PRESET_FIELD_LABELS[attribute])
            label.setProperty("role", "heading")
            label.setBuddy(widget)
            column.addWidget(label)
        control = QHBoxLayout()
        control.addWidget(widget, 1)
        for extra in extras:
            control.addWidget(extra)
        column.addLayout(control)
        PresetListPanel._add_error_label(column, row, attribute)

    @staticmethod
    def _add_error_label(column: QVBoxLayout, row: _PresetRow, attribute: str) -> None:
        """欄の下に出すエラーの文（初めは隠す）を足す。"""
        error_label = QLabel()
        error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()
        column.addWidget(error_label)
        row.error_labels[attribute] = error_label


def _checked(widget: QWidget) -> bool:
    """チェックボックスの今の状態を返す。"""
    assert isinstance(widget, QCheckBox)  # noqa: S101 真偽値の欄はチェックボックスで作る
    return widget.isChecked()


def _text(widget: QWidget) -> str:
    """文字の欄の今の値（前後の空白を除く）を返す。"""
    assert isinstance(widget, QLineEdit)  # noqa: S101 文字の欄は QLineEdit で作る
    return widget.text().strip()


def _hotkey(widget: QWidget) -> str:
    """ホットキーの欄の今の値（pynput の書式。空は空文字）を返す。"""
    hotkey = getattr(widget, "hotkey", None)
    assert isinstance(hotkey, str)  # noqa: S101 ホットキーの欄は HotkeyEdit で作る
    return hotkey


def _set_invalid(widget: QWidget, *, invalid: bool) -> None:
    """欄の枠をエラーの色にする・戻す。"""
    widget.setProperty("invalid", invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
