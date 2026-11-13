"""tokens.toml（デザイン方針の色・書体・余白）から、アプリ全体のスタイルシート（QSS）を作る。"""

from __future__ import annotations

import hashlib
import logging
import tomllib
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from voice_paste.ui.indicator_style import IndicatorStyle

logger = logging.getLogger(__name__)

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
QFrame[role="window"] {
    background-color: @surface@;
    border: 1px solid @frame@;
    border-radius: @radius@px;
}
QFrame[role="shortcut_row"][added="true"] { background-color: @added_bg@; border-radius: @radius@px; }
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
QPushButton[role="hotkey_button"][overhang="true"] { margin: @badge_overhang@px @badge_overhang@px 0 0; }
QPushButton[role="hotkey_button"]:checked {
    background-color: @sunken@;
    border-color: @accent_fg@;
}
QFrame[role="divider"] { background-color: @border@; border: none; min-height: 1px; max-height: 1px; }
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
    border-color: @on_primary_line@;
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
QCheckBox, QRadioButton {
    background: transparent;
    spacing: @indicator_gap@px;
    padding: 2px 6px;
    border: 1px solid transparent;
    border-radius: @radius@px;
}
QCheckBox:focus, QRadioButton:focus { border-color: @accent_fg@; }
QCheckBox:disabled, QRadioButton:disabled { color: @text_muted@; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@arrow_url@"); width: 10px; height: 10px; }
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
QProgressBar[over="true"]::chunk { background-color: @danger@; }
QListWidget {
    background-color: @surface@;
    border: 1px solid @border@;
    border-radius: @radius@px;
    outline: 0;
}
QListWidget::item { padding: 8px 12px; }
QListWidget::item:selected { background-color: @primary@; color: @on_primary@; }
QMenu { background-color: @surface@; border: 1px solid @frame@; }
QMenu::item:selected { background-color: @primary@; color: @on_primary@; }
QMenu::item:disabled { color: @text_muted@; }
QMessageBox { background-color: @surface@; }
QScrollArea { border: none; }
"""
"""アプリ全体の QSS の雛形。色・書体・余白は `@名前@` で置き、tokens.toml の値を埋める。"""

ARROW_SVG_TEMPLATE: str = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<path d="M2 3.5l3 3 3-3" fill="none" stroke="{color}" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
"""選択欄の開くマーカー（V 字）の SVG の雛形。線の色を `{color}` に埋める。"""

ARROW_IMAGE_HASH_LENGTH: int = 16
"""開くマーカーの画像のファイル名に使う、中身のハッシュの文字数。"""


@cache
def load_tokens() -> dict[str, Any]:
    """tokens.toml を読む。"""
    return tomllib.loads(TOKENS_FILE.read_text(encoding="utf-8"))


def _font_family(fonts: list[str]) -> str:
    """書体の候補の並びを、QSS の font-family の値（引用符で囲んでカンマで並べた文字）にする。"""
    return ", ".join(f'"{font}"' for font in fonts)


def write_arrow_image(dark: bool, *, image_dir: Path) -> Path:
    """選択欄の開くマーカー（text_muted の線の V 字）を明暗の組の色で SVG にして image_dir に書き、そのパスを返す。"""
    color = load_tokens()["color"]["dark" if dark else "light"]["text_muted"]
    svg = ARROW_SVG_TEMPLATE.format(color=color)
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()[:ARROW_IMAGE_HASH_LENGTH]
    image = image_dir / f"{digest}.svg"
    # 同じ中身のファイルがあれば書き直さない
    if not image.exists():
        image_dir.mkdir(parents=True, exist_ok=True)
        image.write_text(svg, encoding="utf-8")
    return image


def build_stylesheet(dark: bool, *, image_dir: Path) -> str:
    """明暗に合う色のトークンと、書体・大きさ・余白のトークンを QSS の雛形に埋めて返す。開くマーカーの画像は image_dir に書く。"""
    tokens = load_tokens()
    colors: dict[str, str] = tokens["color"]["dark" if dark else "light"]

    # 置き換える名前と値の対応を作る（色は名前のまま、書体・大きさ・形状は分類の接頭辞を付ける）
    values: dict[str, str] = dict(colors)
    values["font_ui"] = _font_family(tokens["font"]["ui"])
    values["font_mono"] = _font_family(tokens["font"]["mono"])
    values.update({f"size_{name}": str(value) for name, value in tokens["size"].items()})
    values.update({name: str(value) for name, value in tokens["shape"].items()})
    # url() には `\` 区切りでは描かれないため、`/` 区切りのパスを入れる
    values["arrow_url"] = write_arrow_image(dark, image_dir=image_dir).as_posix()

    stylesheet = QSS_TEMPLATE
    for name, value in values.items():
        stylesheet = stylesheet.replace(PLACEHOLDER_FORMAT.format(name=name), value)
    return stylesheet


def is_dark_theme() -> bool:
    """OS が暗いテーマかを返す。"""
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def resolve_dark(theme: Literal["system", "light", "dark"], system_dark: bool) -> bool:
    """ui.theme と OS の明暗から、暗い組の色を使うかを決める。`light` は False、`dark` は True、`system` は OS の明暗に従う。"""
    if theme == "system":
        return system_dark
    return theme == "dark"


_current_dark: bool | None = None
"""apply_theme が当てた明暗（暗い組か）。まだ当てていなければ None（書くのは apply_theme だけ）。"""

_indicator_style: IndicatorStyle | None = None
"""apply_theme が当てた IndicatorStyle。まだ当てていなければ None（書くのは apply_theme だけ）。"""


def apply_theme(
    app: QApplication, theme: Literal["system", "light", "dark"], *, image_dir: Path
) -> None:
    """ui.theme で決めた明暗のスタイルシートをアプリ全体に当て、開いている窓を描き直す。メインスレッドから呼ぶ。"""
    global _current_dark, _indicator_style  # noqa: PLW0603
    # スタイルシートで塗らない部品（スクロールバーなど）は style がパレットで描くため、Qt の明暗も揃える
    hints = app.styleHints()
    if theme == "system":
        hints.unsetColorScheme()
    else:
        hints.setColorScheme(Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light)
    dark = resolve_dark(theme, is_dark_theme())
    _current_dark = dark
    # マーカーを描くスタイルは 1 回だけ当てる（スタイルシートを当てると app.style() は Qt の内部のスタイルに替わるため、当てたかは控えで見る）
    if _indicator_style is None:
        # IndicatorStyle は theme_color を使うため、循環 import を避けてここで読む
        from voice_paste.ui.indicator_style import IndicatorStyle

        _indicator_style = IndicatorStyle(app.style())
        app.setStyle(_indicator_style)
    app.setStyleSheet(build_stylesheet(dark, image_dir=image_dir))
    # 状態のマーカー・波形・回るマーカーは theme_color で描くため、開いている窓を描き直して新しい組の色にする
    for widget in QApplication.topLevelWidgets():
        widget.update()
    logger.info(f"画面の明暗を当てた（theme={theme}・暗い組={dark}）")


def theme_color(name: str) -> QColor:
    """apply_theme で当てた明暗の組の色のトークンを、描画に使う色で返す。まだ当てていなければ OS の明暗の組を使う。"""
    dark = is_dark_theme() if _current_dark is None else _current_dark
    colors: dict[str, str] = load_tokens()["color"]["dark" if dark else "light"]
    return QColor(colors[name])
