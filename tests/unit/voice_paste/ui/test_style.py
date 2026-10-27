"""ui/style.py（build_stylesheet・write_arrow_image・resolve_dark・apply_theme・theme_color）と ui/indicator_style.py（IndicatorStyle）の単体テスト。

apply_theme を呼ぶテストは offscreen の QApplication（conftest の qapp）で動かし、OS の明暗（is_dark_theme）は差し替える。
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, call

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QProxyStyle,
    QRadioButton,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QStyleOptionButton,
    QStyleOptionFocusRect,
    QWidget,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


@pytest.fixture
def tokens(repo_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """src/voice_paste/ui/tokens.toml を読んだ値を返す。"""
    tokens_file = repo_root / "src" / "voice_paste" / "ui" / "tokens.toml"
    return tomllib.loads(tokens_file.read_text(encoding="utf-8"))


@pytest.fixture
def shape_tokens(tokens: dict[str, dict[str, dict[str, str]]]) -> dict[str, int]:
    """tokens.toml の `[shape]`（大きさ・間の値。整数）を返す。"""
    return cast("dict[str, int]", tokens["shape"])


def _plain_style_name(app: QApplication) -> str:
    """アプリのスタイルの名前を返す（スタイルを包んでいれば、包まれた元のスタイルの名前）。"""
    style = app.style()
    if isinstance(style, QProxyStyle):
        return style.baseStyle().objectName()
    return style.objectName()


@pytest.fixture
def theme_app(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """apply_theme が控える明暗と IndicatorStyle を未設定にした QApplication を返し、テストの後にスタイルシートと Qt の明暗の上書きとアプリのスタイルを元に戻す。"""
    from voice_paste.ui import style as style_module

    monkeypatch.setattr("voice_paste.ui.style._current_dark", None, raising=False)
    style_name = _plain_style_name(qapp)
    qapp.setStyle(QStyleFactory.create(style_name))
    style_module._indicator_style = None
    yield qapp
    qapp.setStyleSheet("")
    qapp.styleHints().unsetColorScheme()
    qapp.setStyle(QStyleFactory.create(style_name))
    style_module._indicator_style = None


def _rule_body(stylesheet: str, selector: str) -> str:
    """QSS から、行頭のセレクタの規則の中身（`{` と `}` の間）を返す。"""
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet)
    assert match is not None, f"{selector} の規則が無い"
    return match.group(1)


def _rule_body_of(stylesheet: str, selector: str) -> str:
    """QSS から、カンマで並べたセレクタの 1 つに selector を持つ規則の中身を、全て連ねて返す。"""
    bodies = [
        body
        for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", stylesheet)
        if selector in [part.strip() for part in selectors.split(",")]
    ]
    assert bodies, f"{selector} の規則が無い"
    return "\n".join(bodies)


def test_build_stylesheet(tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path) -> None:
    """明暗ごとのトークンを埋める（正常系）。"""
    from voice_paste.ui.style import build_stylesheet

    # 実行
    dark_qss = build_stylesheet(True, image_dir=tmp_path)
    light_qss = build_stylesheet(False, image_dir=tmp_path)

    # 検証
    assert tokens["color"]["dark"]["bg"] in dark_qss
    assert tokens["color"]["light"]["bg"] not in dark_qss
    assert tokens["color"]["light"]["bg"] in light_qss
    assert tokens["color"]["dark"]["bg"] not in light_qss
    assert dark_qss.count("{") == dark_qss.count("}")
    assert light_qss.count("{") == light_qss.count("}")


def test_build_stylesheet_when_window_frame(
    tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """枠なしの窓とメニューの縁を frame で描く（正常系）。"""
    from voice_paste.ui.style import build_stylesheet

    # 実行
    light_qss = build_stylesheet(False, image_dir=tmp_path)

    # 検証
    light = tokens["color"]["light"]
    assert light["frame"] in _rule_body(light_qss, 'QFrame[role="window"]')
    assert light["frame"] in _rule_body(light_qss, "QMenu")
    surface_rule = _rule_body(light_qss, 'QFrame[role="surface"]')
    assert light["border"] in surface_rule
    assert light["frame"] not in surface_rule
    assert "@" not in light_qss


def test_build_stylesheet_when_check_indicator(
    tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """チェックボックス・ラジオボタンのフォーカスの枠と選択欄の開くマーカーの区画の規則を持ち、マーカーの規則を持たない（正常系）。"""
    from voice_paste.ui.style import build_stylesheet, write_arrow_image

    # 準備: 空白を含むフォルダに画像を書かせる
    image_dir = tmp_path / "ui images"

    # 実行
    light_qss = build_stylesheet(False, image_dir=image_dir)

    # 検証
    light = tokens["color"]["light"]
    arrow_image = write_arrow_image(False, image_dir=image_dir)
    down_arrow_rule = _rule_body_of(light_qss, "QComboBox::down-arrow")
    assert light["accent_fg"] in _rule_body_of(light_qss, "QCheckBox:focus")
    assert light["accent_fg"] in _rule_body_of(light_qss, "QRadioButton:focus")
    assert _rule_body_of(light_qss, "QComboBox::drop-down")
    assert f'url("{arrow_image.as_posix()}")' in down_arrow_rule
    assert "\\" not in down_arrow_rule
    assert "::indicator" not in light_qss


def test_write_arrow_image(tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path) -> None:
    """明暗ごとの色で V 字の SVG を書く（正常系）。"""
    from voice_paste.ui.style import write_arrow_image

    # 準備: まだ無いフォルダに書かせる
    image_dir = tmp_path / "ui"

    # 実行
    dark_image = write_arrow_image(True, image_dir=image_dir)
    light_image = write_arrow_image(False, image_dir=image_dir)

    # 検証
    dark_muted = tokens["color"]["dark"]["text_muted"]
    light_muted = tokens["color"]["light"]["text_muted"]
    assert image_dir.is_dir()
    assert dark_image != light_image
    assert dark_image.parent == image_dir
    assert light_image.parent == image_dir
    assert dark_muted in dark_image.read_text(encoding="utf-8").lower()
    assert light_muted in light_image.read_text(encoding="utf-8").lower()


# === resolve_dark ===


def test_resolve_dark_when_light() -> None:
    """light は OS によらず明るい組（正常系）。"""
    from voice_paste.ui.style import resolve_dark

    # 実行
    result = resolve_dark("light", True)

    # 検証
    assert result is False


def test_resolve_dark_when_dark() -> None:
    """dark は OS によらず暗い組（正常系）。"""
    from voice_paste.ui.style import resolve_dark

    # 実行
    result = resolve_dark("dark", False)

    # 検証
    assert result is True


@pytest.mark.parametrize(
    ("system_dark", "expected"),
    [pytest.param(True, True, id="os_dark"), pytest.param(False, False, id="os_light")],
)
def test_resolve_dark_when_system(system_dark: bool, expected: bool) -> None:
    """system は OS の明暗に従う（正常系）。"""
    from voice_paste.ui.style import resolve_dark

    # 実行
    result = resolve_dark("system", system_dark)

    # 検証
    assert result is expected


# === apply_theme ===


def test_apply_theme_when_dark(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """dark を当てると OS が明るくても暗い組になる（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))

    # 実行
    apply_theme(theme_app, "dark", image_dir=tmp_path)

    # 検証
    assert tokens["color"]["dark"]["bg"] in theme_app.styleSheet()
    assert tokens["color"]["light"]["bg"] not in theme_app.styleSheet()
    assert theme_color("surface") == QColor(tokens["color"]["dark"]["surface"])


def test_apply_theme_when_system(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """system は OS の明暗に従う（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=True))

    # 実行
    apply_theme(theme_app, "system", image_dir=tmp_path)

    # 検証
    assert tokens["color"]["dark"]["bg"] in theme_app.styleSheet()
    assert tokens["color"]["light"]["bg"] not in theme_app.styleSheet()
    assert theme_color("surface") == QColor(tokens["color"]["dark"]["surface"])


def test_apply_theme_when_switched(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """当て直すと開いている窓の色も変わる（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備: dark を当てて窓を 1 つ出す
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))
    apply_theme(theme_app, "dark", image_dir=tmp_path)
    window = QWidget()
    window.show()
    update = MagicMock()
    monkeypatch.setattr(window, "update", update)

    # 実行
    apply_theme(theme_app, "light", image_dir=tmp_path)

    # 検証
    window.close()
    assert tokens["color"]["light"]["bg"] in theme_app.styleSheet()
    assert tokens["color"]["dark"]["bg"] not in theme_app.styleSheet()
    assert theme_color("surface") == QColor(tokens["color"]["light"]["surface"])
    update.assert_called()


@pytest.mark.parametrize(
    ("theme", "expected_calls"),
    [
        pytest.param(
            "light",
            [call.hints.setColorScheme(Qt.ColorScheme.Light), call.is_dark_theme()],
            id="light",
        ),
        pytest.param(
            "dark",
            [call.hints.setColorScheme(Qt.ColorScheme.Dark), call.is_dark_theme()],
            id="dark",
        ),
        pytest.param(
            "system", [call.hints.unsetColorScheme(), call.is_dark_theme()], id="system"
        ),
    ],
)
def test_apply_theme_when_color_scheme(
    theme_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    theme: str,
    expected_calls: list[object],
) -> None:
    """light・dark は Qt の明暗を上書きし、system は上書きを外してから OS の明暗を読む（正常系）。"""
    from voice_paste.ui.style import apply_theme

    # 準備: styleHints と is_dark_theme を 1 つの Mock にまとめ、呼ばれた順を見る
    recorder = MagicMock()
    hints = MagicMock()
    is_dark_theme = MagicMock(return_value=False)
    recorder.attach_mock(hints, "hints")
    recorder.attach_mock(is_dark_theme, "is_dark_theme")
    monkeypatch.setattr(theme_app, "styleHints", lambda: hints)
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", is_dark_theme)

    # 実行
    apply_theme(theme_app, theme, image_dir=tmp_path)

    # 検証
    assert recorder.mock_calls == expected_calls


def test_apply_theme_when_indicator_style(
    theme_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """IndicatorStyle を 1 回だけ当てる（正常系）。"""
    from voice_paste.ui import style as style_module
    from voice_paste.ui.indicator_style import IndicatorStyle
    from voice_paste.ui.style import apply_theme

    # 準備: setStyle の呼び出しを数える
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))
    set_style = MagicMock(wraps=theme_app.setStyle)
    monkeypatch.setattr(theme_app, "setStyle", set_style)

    # 実行
    apply_theme(theme_app, "light", image_dir=tmp_path)
    first_style = style_module._indicator_style
    apply_theme(theme_app, "dark", image_dir=tmp_path)
    second_style = style_module._indicator_style

    # 検証
    assert isinstance(first_style, IndicatorStyle)
    assert second_style is first_style
    assert set_style.call_count == 1


# === theme_color ===


def test_theme_color_when_not_applied(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_theme の前は OS の明暗の組（正常系）。"""
    from voice_paste.ui.style import theme_color

    # 準備
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=True))

    # 実行
    color = theme_color("busy")

    # 検証
    assert color == QColor(tokens["color"]["dark"]["busy"])


def test_theme_color_when_applied(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """apply_theme の後は当てた明暗の組（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備: OS は暗いが light を当てる
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=True))
    apply_theme(theme_app, "light", image_dir=tmp_path)

    # 実行
    color = theme_color("busy")

    # 検証
    assert color == QColor(tokens["color"]["light"]["busy"])


# === IndicatorStyle ===

GRAB_SIZE: int = 40
"""マーカーを描いた部品を画像にするときの一辺（論理ピクセル。16px のマーカーの周りに余白を持たせる）。"""

COLOR_TOLERANCE: int = 6
"""同じ色とみなす、赤・緑・青のそれぞれの差の上限（縁のなだらかな混ざりを許す）。"""

HALF_ALPHA: int = 128
"""縁の画素のうち、色を比べる不透明度の下限（これ未満は背景の透明が混ざりすぎる）。"""

OPAQUE_ALPHA: int = 255
"""完全に塗られた画素の不透明度。"""


class _RecordingStyle(QProxyStyle):
    """drawPrimitive の呼び出しを控えて、包んだスタイルへ渡すスタイル。"""

    def __init__(self, base: QStyle) -> None:
        super().__init__(base)
        self.draw_calls: list[tuple[QStyle.PrimitiveElement, QStyleOption, QPainter, QWidget | None]] = []

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        """呼び出しを控えてから、包んだスタイルで描く。"""
        self.draw_calls.append((element, option, painter, widget))
        super().drawPrimitive(element, option, painter, widget)


def _grab(widget: QWidget) -> QImage:
    """部品を GRAB_SIZE 四方にして画像に描く（背景は透明のまま）。"""
    widget.resize(GRAB_SIZE, GRAB_SIZE)
    return widget.grab().toImage()


def _distance(color: QColor, hex_color: str) -> int:
    """2 色の、赤・緑・青のそれぞれの差の最大を返す。"""
    other = QColor(hex_color)
    return max(
        abs(color.red() - other.red()),
        abs(color.green() - other.green()),
        abs(color.blue() - other.blue()),
    )


def _pixel_colors(image: QImage) -> list[QColor]:
    """画像の全ての画素の色を返す。"""
    return [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]


def _count_near(image: QImage, hex_color: str) -> int:
    """画像のうち、半分以上が塗られた画素で、色が hex_color に近いものの数を返す。"""
    return sum(
        1
        for color in _pixel_colors(image)
        if color.alpha() >= HALF_ALPHA and _distance(color, hex_color) <= COLOR_TOLERANCE
    )


def _count_closer(image: QImage, hex_color: str, other_hex_color: str) -> int:
    """画像のうち、完全に塗られた画素で、other_hex_color より hex_color に近いものの数を返す。"""
    return sum(
        1
        for color in _pixel_colors(image)
        if color.alpha() == OPAQUE_ALPHA
        and _distance(color, hex_color) < _distance(color, other_hex_color)
    )


def _radio_center_color(radio: QRadioButton) -> QColor:
    """ラジオボタンを画像に描き、丸の中心の画素の色を返す。"""
    image = _grab(radio)
    option = QStyleOptionButton()
    option.initFrom(radio)
    rect = radio.style().subElementRect(QStyle.SubElement.SE_RadioButtonIndicator, option, radio)
    scale = image.devicePixelRatio()
    return image.pixelColor(
        int((rect.x() + rect.width() / 2) * scale), int((rect.y() + rect.height() / 2) * scale)
    )


def test_draw_checkbox_when_on(
    theme_app: QApplication, tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """オンの箱を accent_fg で塗りチェックを surface で描く（正常系）。"""
    from voice_paste.ui.style import apply_theme

    # 準備
    apply_theme(theme_app, "light", image_dir=tmp_path)
    checkbox = QCheckBox()
    checkbox.setChecked(True)

    # 実行
    image = _grab(checkbox)

    # 検証
    light = tokens["color"]["light"]
    assert _count_near(image, light["accent_fg"]) > 0
    assert _count_closer(image, light["surface"], light["accent_fg"]) > 0


def test_draw_checkbox_when_off(
    theme_app: QApplication, tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """オフの箱は塗らず text_muted の線で囲む（正常系）。"""
    from voice_paste.ui.style import apply_theme

    # 準備
    apply_theme(theme_app, "dark", image_dir=tmp_path)
    checkbox = QCheckBox()

    # 実行
    image = _grab(checkbox)

    # 検証
    dark = tokens["color"]["dark"]
    assert _count_near(image, dark["text_muted"]) > 0
    assert _count_near(image, dark["accent_fg"]) == 0


def test_draw_checkbox_when_disabled(
    theme_app: QApplication, tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """使えないオンの箱を border で塗りチェックを text_muted で描く（正常系）。"""
    from voice_paste.ui.style import apply_theme

    # 準備
    apply_theme(theme_app, "light", image_dir=tmp_path)
    checkbox = QCheckBox()
    checkbox.setChecked(True)
    checkbox.setEnabled(False)

    # 実行
    image = _grab(checkbox)

    # 検証
    light = tokens["color"]["light"]
    assert _count_near(image, light["border"]) > 0
    assert _count_closer(image, light["text_muted"], light["border"]) > 0
    assert _count_near(image, light["accent_fg"]) == 0


def test_draw_radio_when_checked(
    theme_app: QApplication, tokens: dict[str, dict[str, dict[str, str]]], tmp_path: Path
) -> None:
    """選んだラジオボタンに accent_fg の点を描く（正常系）。"""
    from voice_paste.ui.style import apply_theme

    # 準備: 選んだボタンと選んでいないボタンを別々の部品にする
    apply_theme(theme_app, "dark", image_dir=tmp_path)
    checked = QRadioButton()
    checked.setChecked(True)
    unchecked = QRadioButton()

    # 実行
    checked_center = _radio_center_color(checked)
    unchecked_center = _radio_center_color(unchecked)

    # 検証
    accent_fg = tokens["color"]["dark"]["accent_fg"]
    assert _distance(checked_center, accent_fg) <= COLOR_TOLERANCE
    assert _distance(unchecked_center, accent_fg) > COLOR_TOLERANCE


def test_draw_primitive_when_other(qapp: QApplication) -> None:
    """マーカーでない要素は包んだスタイルへ渡す（正常系）。"""
    from voice_paste.ui.indicator_style import IndicatorStyle

    # 準備: 呼び出しを控えるスタイルを包ませる
    wrapped = _RecordingStyle(QStyleFactory.create("fusion"))
    style = IndicatorStyle(wrapped)
    option = QStyleOptionFocusRect()
    option.rect = QRect(0, 0, 10, 10)
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    painter = QPainter(image)

    # 実行
    style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, option, painter, None)
    painter.end()

    # 検証
    assert len(wrapped.draw_calls) == 1
    element, passed_option, passed_painter, passed_widget = wrapped.draw_calls[0]
    assert element == QStyle.PrimitiveElement.PE_FrameFocusRect
    assert passed_option is option
    assert passed_painter is painter
    assert passed_widget is None


@pytest.mark.parametrize(
    "metric",
    [
        pytest.param(QStyle.PixelMetric.PM_IndicatorWidth, id="indicator_width"),
        pytest.param(QStyle.PixelMetric.PM_IndicatorHeight, id="indicator_height"),
        pytest.param(QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, id="exclusive_width"),
        pytest.param(QStyle.PixelMetric.PM_ExclusiveIndicatorHeight, id="exclusive_height"),
    ],
)
def test_pixel_metric_when_indicator(
    qapp: QApplication, shape_tokens: dict[str, int], metric: QStyle.PixelMetric
) -> None:
    """マーカーの大きさを tokens.toml から返す（正常系）。"""
    from voice_paste.ui.indicator_style import IndicatorStyle

    # 準備
    style = IndicatorStyle(QStyleFactory.create("fusion"))

    # 実行
    result = style.pixelMetric(metric)

    # 検証
    assert result == shape_tokens["indicator"]


def test_pixel_metric_when_other(qapp: QApplication) -> None:
    """ほかの大きさは包んだスタイルの値（正常系）。"""
    from voice_paste.ui.indicator_style import IndicatorStyle

    # 準備: 同じスタイルを包んだものと包まないものを用意する
    plain = QStyleFactory.create("fusion")
    style = IndicatorStyle(QStyleFactory.create("fusion"))

    # 実行
    result = style.pixelMetric(QStyle.PixelMetric.PM_ButtonMargin)

    # 検証
    assert result == plain.pixelMetric(QStyle.PixelMetric.PM_ButtonMargin)
