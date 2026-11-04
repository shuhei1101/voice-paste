"""設定画面の欄の部品（型から決まる部品）と、設定のキーの扱い。"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSlider,
    QWidget,
)

from voice_paste.shared.settings import RELOAD_IMMEDIATE, Settings
from voice_paste.ui.style import load_tokens

KEY_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"\[(\d+)\]|([^.\[\]]+)")
"""設定のキー（`outputs[0].enter_delay_sec`）を、添字と名前に分ける。"""

SLIDER_MAX: int = 100
"""音量の割合のつまみの最大（%）。"""

CHOICE_PROPERTY: str = "choice"
"""チェックボックスの組で、各チェックボックスが持つ列挙の値の property 名。"""

WHISPER_MODEL_CHOICES: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")
"""文字起こしのモデルの選択の欄に並べる、よく使うモデルの名前（ここに無い名前も入れられる）。"""


@dataclass
class Field:
    """設定のキー 1 つの欄。キーは添字が変わる欄（送信先の行）のために、あとから変更できる。"""

    key: str
    """設定のキー（エラーの一覧と同じ書式）。"""

    label: str
    """欄の名前（設定の設計書の論理名を画面向けにしたもの）。"""

    reload: str
    """反映の仕方（immediate か restart）。"""

    widget: QWidget
    """値を持つ部品。objectName は `field_{key}`。"""

    get: Callable[[], Any]
    """部品の今の値を、Settings.model_validate へ渡す値で返す。"""

    group: int
    """欄があるまとまりの番号（まとまりのメニューの並び）。"""

    error_label: QLabel | None = None
    """欄の下に出すエラーの文。"""


def key_tokens(key: str) -> list[int | str]:
    """設定のキーを、名前（str）と添字（int）の並びにする。"""
    return [
        int(index) if index else name for index, name in KEY_TOKEN_PATTERN.findall(key)
    ]


def set_nested(data: dict[str, Any], key: str, value: Any) -> None:
    """設定のキーの場所に value を置く（途中の dict・list は無ければ作る）。添字は前から順に埋まる前提。"""
    tokens = key_tokens(key)
    container: Any = data
    for position, token in enumerate(tokens):
        is_last = position == len(tokens) - 1
        next_token = None if is_last else tokens[position + 1]
        if isinstance(token, int):
            # 添字: 足りない分の要素を作ってから、その要素を辿る
            while len(container) <= token:
                container.append({})
            if is_last:
                container[token] = value
            else:
                container = container[token]
        elif is_last:
            container[token] = value
        else:
            # 名前: 無ければ次が添字なら list、そうでなければ dict を作って辿る
            container = container.setdefault(token, [] if isinstance(next_token, int) else {})


def value_at(settings: Settings, key: str) -> Any:
    """設定のキーの値を引く（`outputs[0].enter_delay_sec` のように添字を含んでよい）。"""
    value: Any = settings
    for token in key_tokens(key):
        value = value[token] if isinstance(token, int) else getattr(value, token)
    return value


def reload_of(key: str) -> str:
    """設定のキーの反映の仕方を、設定のモデルの項目のマーカーから引く（マーカーが無ければ immediate）。"""
    model: Any = Settings
    reload = RELOAD_IMMEDIATE
    for token in key_tokens(key):
        fields = getattr(model, "model_fields", None)
        if isinstance(token, int) or fields is None or token not in fields:
            break
        info = fields[token]
        extra = info.json_schema_extra
        if isinstance(extra, dict) and "reload" in extra:
            reload = str(extra["reload"])
        model = info.annotation
    return reload


def connect_changed(widget: QWidget, slot: Callable[[], None]) -> None:
    """部品の値が変わったら slot を呼ぶ（部品の種類ごとの変更の Signal につなぐ）。"""
    if isinstance(widget, QCheckBox):
        widget.toggled.connect(lambda _checked: slot())
    elif isinstance(widget, QSlider):
        widget.valueChanged.connect(lambda _value: slot())
    elif isinstance(widget, QComboBox):
        widget.currentTextChanged.connect(lambda _text: slot())
    elif isinstance(widget, QPlainTextEdit):
        widget.textChanged.connect(slot)
    elif isinstance(widget, QLineEdit):
        widget.textChanged.connect(lambda _text: slot())
    else:
        # ラジオボタンの組・チェックボックスの組（部品を束ねた QWidget）は、中のボタンの切り替えにつなぐ
        for button in widget.findChildren(QAbstractButton):
            button.toggled.connect(lambda _checked: slot())


def make_check_box(label: str, checked: bool) -> QCheckBox:
    """チェックボックスを作る。"""
    return QCheckBox(label, checked=checked)


def make_check_box_group(
    key: str, choices: Sequence[str], labels: Mapping[str, str], current: Sequence[str]
) -> QWidget:
    """列挙の値ごとのチェックボックスを、横に並べた QWidget にして返す。各チェックボックスの objectName は `field_{キー}_{値}`、オンにした値は `checked_choices` で読む。"""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    for choice in choices:
        check_box = make_check_box(labels.get(choice, choice), choice in current)
        check_box.setObjectName(f"field_{key}_{choice}")
        check_box.setProperty(CHOICE_PROPERTY, choice)
        layout.addWidget(check_box)
    layout.addStretch(1)
    return container


def checked_choices(container: QWidget) -> list[str]:
    """チェックボックスの組で、オンにした値を列挙の並びで返す。"""
    return [
        str(check_box.property(CHOICE_PROPERTY))
        for check_box in container.findChildren(QCheckBox)
        if check_box.isChecked()
    ]


def make_line_edit(text: str) -> QLineEdit:
    """文字の欄（数値の欄も、確かめは保存のときに設定のモデルで行うため文字のまま受ける）を作る。"""
    return QLineEdit(text)


def make_slider(value: float) -> QSlider:
    """0〜100 のつまみを作る（右に % を出すのは呼ぶ側）。"""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, SLIDER_MAX)
    slider.setValue(round(value))
    return slider


def make_combo(
    choices: tuple[str, ...],
    current: str,
    *,
    editable: bool,
    labels: Mapping[str, str] | None = None,
) -> QComboBox:
    """選択の欄を作る。editable なら選択肢に無い名前も入れられる。labels（値 → 名前）を渡すと、名前を出して値を項目に持たせる。選んだ値は `selected_combo` で読む。"""
    combo = QComboBox()
    combo.setEditable(editable)
    items = list(choices) if current in choices else [*choices, current]
    for item in items:
        combo.addItem((labels or {}).get(item, item), item)
    combo.setCurrentIndex(combo.findData(current))
    return combo


def selected_combo(combo: QComboBox) -> str:
    """選択の欄で選んだ値を返す。編集できる欄は入れた文字、編集できない欄は選んだ項目に持たせた値。"""
    if combo.isEditable():
        return combo.currentText()
    return str(combo.currentData())


def make_radio_group(
    choices: tuple[str, ...], current: str, *, labels: Mapping[str, str] | None = None
) -> QWidget:
    """ラジオボタンの組を、横に並べた QWidget にして返す。ボタンの名前は labels（無い値は値そのまま）で、値はボタンに持たせる。選んだ値は `selected_radio` で読む。"""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    # 選択肢の間は、マーカーと名前の間より広くして、丸がどの名前のマーカーかを距離で分ける
    layout.setSpacing(int(load_tokens()["shape"]["choice_gap"]))
    group = QButtonGroup(container)
    for choice in choices:
        button = QRadioButton((labels or {}).get(choice, choice))
        button.setProperty(CHOICE_PROPERTY, choice)
        button.setChecked(choice == current)
        group.addButton(button)
        layout.addWidget(button)
    layout.addStretch(1)
    return container


def selected_radio(container: QWidget) -> str:
    """ラジオボタンの組で、選んでいるボタンの値（名前ではなく列挙の値）を返す。"""
    for button in container.findChildren(QRadioButton):
        if button.isChecked():
            return button.property(CHOICE_PROPERTY)
    return ""


def make_plain_text(lines: list[str]) -> QPlainTextEdit:
    """複数行の文字の欄を、1 行 1 要素で作る。"""
    edit = QPlainTextEdit("\n".join(lines))
    edit.setFixedHeight(96)
    return edit


def plain_text_lines(edit: QPlainTextEdit) -> list[str]:
    """複数行の文字の欄を、空行を除いた行の一覧にする。"""
    return [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]


def set_invalid(widget: QWidget, *, invalid: bool) -> None:
    """欄の枠をエラーの色にする・戻す。"""
    widget.setProperty("invalid", invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
