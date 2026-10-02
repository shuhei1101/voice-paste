"""用語集の行。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class GlossaryEntry:
    """誤変換と正しい表記の組。"""

    wrong: str
    """誤変換（CSV の列 `誤変換`）。"""

    right: str
    """正しい表記（CSV の列 `正しい表記`）。"""
