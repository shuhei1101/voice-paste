"""tokens.toml（デザイン方針の色・書体・余白）から、アプリ全体のスタイルシート（QSS）を作る。"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

TOKENS_FILE: Path = Path(__file__).with_name("tokens.toml")
"""色・書体・余白のトークンのファイル。"""

PLACEHOLDER_FORMAT: str = "@{name}@"
"""QSS の雛形で、トークンの値に置き換える場所の書式。"""

QSS_TEMPLATE: str = """
QWidget {
    background-color: @bg@;
    color: @text@;
    font-family: @font_ui@;
    font-size: @size_text@px;
}
QLabel { background: transparent; }
QLabel[role="muted"] { color: @text_muted@; font-size: @size_text_small@px; }
QLabel[role="mono"] { font-family: @font_mono@; font-size: @size_text_key@px; color: @text_muted@; }
QLabel[role="time"] { font-family: @font_mono@; font-size: @size_time@px; }
QLabel[role="heading"] { font-weight: 600; }
QLabel[role="error"] { color: @danger@; font-size: @size_text_small@px; }
QLabel[role="recording"] { color: @recording@; font-weight: 600; }
QLabel[role="paused"] { color: @paused@; font-weight: 600; }
QLabel[role="busy"] { color: @busy@; font-weight: 600; }
QLabel[role="notice"] { background-color: @notice_bg@; border-radius: @radius@px; padding: 8px; }
QFrame[role="surface"] {
    background-color: @surface@;
    border: 1px solid @border@;
    border-radius: @radius@px;
}
QFrame[role="alert"] {
    background-color: @danger_bg@;
    border: 1px solid @danger@;
    border-radius: @radius@px;
}
QFrame[role="alert"] QLabel { background: transparent; color: @danger@; }
QPushButton {
    background-color: @surface@;
    color: @text@;
    border: 1px solid @border@;
    border-radius: @radius@px;
    min-height: @control_height@px;
    padding: 0 12px;
}
QPushButton:hover { border-color: @accent_fg@; }
QPushButton:focus { border-color: @accent_fg@; }
QPushButton:disabled { color: @text_muted@; }
QPushButton[primary="true"] {
    background-color: @primary@;
    color: @on_primary@;
    border-color: @primary@;
}
QPushButton[primary="true"]:hover { background-color: @primary_hover@; }
QPushButton QLabel { background: transparent; }
QPushButton[role="hotkey_button"] { padding: 0; }
QPushButton[primary="true"] QLabel { color: @on_primary@; }
QLabel[role="keycap"] {
    font-family: @font_mono@;
    font-size: @size_text_key@px;
    color: @text_muted@;
    background-color: @sunken@;
    border: 1px solid @border@;
    border-bottom: 2px solid @border@;
    border-radius: @radius@px;
    padding: 0 5px;
}
QPushButton[primary="true"] QLabel[role="keycap"] {
    color: @on_primary@;
    background-color: transparent;
    border-color: rgba(255, 255, 255, 90);
}
QWidget[role="head_row"] { background-color: transparent; border-radius: @radius@px; }
QWidget[role="head_row"]:hover { background-color: @sunken@; }
QPushButton[role="head_button"], QPushButton[role="head_close"] {
    background-color: transparent;
    border: 1px solid transparent;
    min-height: 0;
    padding: 0;
}
QPushButton[role="head_button"]:hover { background-color: @surface@; border-color: @border@; }
QPushButton[role="head_close"]:hover { background-color: @danger_bg@; border-color: @danger@; }
QPushButton[role="head_button"]:pressed, QPushButton[role="head_close"]:pressed {
    background-color: @sunken@;
}
QFrame[role="head_divider"] { background-color: @border@; border: none; }
QLineEdit, QPlainTextEdit, QComboBox {
    background-color: @sunken@;
    color: @text@;
    border: 1px solid @border@;
    border-radius: @radius@px;
    min-height: @control_height@px;
    padding: 0 8px;
}
QPlainTextEdit { padding: 6px 8px; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: @accent_fg@; }
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border-color: @danger@; }
QCheckBox, QRadioButton { background: transparent; spacing: 8px; }
QSlider::groove:horizontal { height: 4px; background: @border@; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0;
    background: @primary@; border-radius: 8px;
}
QProgressBar {
    background-color: @sunken@;
    border: 1px solid @border@;
    border-radius: @radius@px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk { background-color: @busy@; border-radius: @radius@px; }
QListWidget {
    background-color: @surface@;
    border: 1px solid @border@;
    border-radius: @radius@px;
    outline: 0;
}
QListWidget::item { padding: 8px 12px; }
QListWidget::item:selected { background-color: @primary@; color: @on_primary@; }
QMenu { background-color: @surface@; border: 1px solid @border@; }
QMenu::item:selected { background-color: @primary@; color: @on_primary@; }
QMenu::item:disabled { color: @text_muted@; }
QMessageBox { background-color: @surface@; }
QScrollArea { border: none; }
"""
"""アプリ全体の QSS の雛形。色・書体・余白は `@名前@` で置き、tokens.toml の値を埋める。"""


@cache
def load_tokens() -> dict[str, Any]:
    """tokens.toml を読む。"""
    return tomllib.loads(TOKENS_FILE.read_text(encoding="utf-8"))


def _font_family(fonts: list[str]) -> str:
    """書体の候補の並びを、QSS の font-family の値（引用符で囲んでカンマで並べた文字）にする。"""
    return ", ".join(f'"{font}"' for font in fonts)


def build_stylesheet(dark: bool) -> str:
    """明暗に合う色のトークンと、書体・大きさ・余白のトークンを QSS の雛形に埋めて返す。"""
    tokens = load_tokens()
    colors: dict[str, str] = tokens["color"]["dark" if dark else "light"]

    # 置き換える名前と値の対応を作る（色は名前のまま、書体・大きさ・形は分類の接頭辞を付ける）
    values: dict[str, str] = dict(colors)
    values["font_ui"] = _font_family(tokens["font"]["ui"])
    values["font_mono"] = _font_family(tokens["font"]["mono"])
    values.update({f"size_{name}": str(value) for name, value in tokens["size"].items()})
    values.update({name: str(value) for name, value in tokens["shape"].items()})

    stylesheet = QSS_TEMPLATE
    for name, value in values.items():
        stylesheet = stylesheet.replace(PLACEHOLDER_FORMAT.format(name=name), value)
    return stylesheet


def is_dark_theme() -> bool:
    """OS が暗いテーマかを返す。"""
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def theme_color(name: str) -> QColor:
    """今のテーマ（明暗）の色のトークンを、描画に使う色で返す。"""
    colors: dict[str, str] = load_tokens()["color"]["dark" if is_dark_theme() else "light"]
    return QColor(colors[name])
