"""ui/style.py（build_stylesheet）の単体テスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def tokens(repo_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """src/voice_paste/ui/tokens.toml を読んだ値を返す。"""
    tokens_file = repo_root / "src" / "voice_paste" / "ui" / "tokens.toml"
    return tomllib.loads(tokens_file.read_text(encoding="utf-8"))


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
