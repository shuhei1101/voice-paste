"""ui/style.py（build_stylesheet・resolve_dark・apply_theme・theme_color）の単体テスト。

apply_theme を呼ぶテストは offscreen の QApplication（conftest の qapp）で動かし、OS の明暗（is_dark_theme）は差し替える。
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


@pytest.fixture
def tokens(repo_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """src/voice_paste/ui/tokens.toml を読んだ値を返す。"""
    tokens_file = repo_root / "src" / "voice_paste" / "ui" / "tokens.toml"
    return tomllib.loads(tokens_file.read_text(encoding="utf-8"))


@pytest.fixture
def theme_app(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """apply_theme が控える明暗を未設定にした QApplication を返し、テストの後にスタイルシートと Qt の明暗の上書きを外す。"""
    monkeypatch.setattr("voice_paste.ui.style._current_dark", None, raising=False)
    yield qapp
    qapp.setStyleSheet("")
    qapp.styleHints().unsetColorScheme()


def _rule_body(stylesheet: str, selector: str) -> str:
    """QSS から、行頭のセレクタの規則の中身（`{` と `}` の間）を返す。"""
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet)
    assert match is not None, f"{selector} の規則が無い"
    return match.group(1)


def test_build_stylesheet(tokens: dict[str, dict[str, dict[str, str]]]) -> None:
    """明暗ごとのトークンを埋める（正常系）。"""
    from voice_paste.ui.style import build_stylesheet

    # 実行
    dark_qss = build_stylesheet(True)
    light_qss = build_stylesheet(False)

    # 検証
    assert tokens["color"]["dark"]["bg"] in dark_qss
    assert tokens["color"]["light"]["bg"] not in dark_qss
    assert tokens["color"]["light"]["bg"] in light_qss
    assert tokens["color"]["dark"]["bg"] not in light_qss
    assert dark_qss.count("{") == dark_qss.count("}")
    assert light_qss.count("{") == light_qss.count("}")


def test_build_stylesheet_when_window_frame(tokens: dict[str, dict[str, dict[str, str]]]) -> None:
    """枠なしの窓とメニューの縁を frame で描く（正常系）。"""
    from voice_paste.ui.style import build_stylesheet

    # 実行
    light_qss = build_stylesheet(False)

    # 検証
    light = tokens["color"]["light"]
    assert light["frame"] in _rule_body(light_qss, 'QFrame[role="window"]')
    assert light["frame"] in _rule_body(light_qss, "QMenu")
    surface_rule = _rule_body(light_qss, 'QFrame[role="surface"]')
    assert light["border"] in surface_rule
    assert light["frame"] not in surface_rule
    assert "@" not in light_qss


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
) -> None:
    """dark を当てると OS が明るくても暗い組になる（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))

    # 実行
    apply_theme(theme_app, "dark")

    # 検証
    assert tokens["color"]["dark"]["bg"] in theme_app.styleSheet()
    assert tokens["color"]["light"]["bg"] not in theme_app.styleSheet()
    assert theme_color("surface") == QColor(tokens["color"]["dark"]["surface"])


def test_apply_theme_when_system(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """system は OS の明暗に従う（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=True))

    # 実行
    apply_theme(theme_app, "system")

    # 検証
    assert tokens["color"]["dark"]["bg"] in theme_app.styleSheet()
    assert tokens["color"]["light"]["bg"] not in theme_app.styleSheet()
    assert theme_color("surface") == QColor(tokens["color"]["dark"]["surface"])


def test_apply_theme_when_switched(
    theme_app: QApplication,
    tokens: dict[str, dict[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当て直すと開いている窓の色も変わる（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備: dark を当てて窓を 1 つ出す
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))
    apply_theme(theme_app, "dark")
    window = QWidget()
    window.show()
    update = MagicMock()
    monkeypatch.setattr(window, "update", update)

    # 実行
    apply_theme(theme_app, "light")

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
    apply_theme(theme_app, theme)

    # 検証
    assert recorder.mock_calls == expected_calls


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
) -> None:
    """apply_theme の後は当てた明暗の組（正常系）。"""
    from voice_paste.ui.style import apply_theme, theme_color

    # 準備: OS は暗いが light を当てる
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=True))
    apply_theme(theme_app, "light")

    # 実行
    color = theme_color("busy")

    # 検証
    assert color == QColor(tokens["color"]["light"]["busy"])
