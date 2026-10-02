"""feature の間を渡る型。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np

type ProgressFn = Callable[[float, float], None]
"""文字起こしの区間の終わりの時刻と録音の長さ（秒）を知らせる関数。"""


class Entry(StrEnum):
    """セッションを始めた入口。"""

    HOTKEY = "hotkey"
    """録音開始のホットキー。"""

    TRAY = "tray"
    """トレイのメニュー。"""

    API = "api"
    """POST /sessions。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class TranscriptionOutcome:
    """出力先へ渡す文字起こしの結果。"""

    session_id: str
    """セッションの ID。"""

    result: Literal["transcribed", "failed", "truncated"]
    """結果の種類。"""

    text: str
    """用語集で補正した文字。空・失敗・打ち切りは空文字。"""

    error: str | None
    """失敗の理由。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording:
    """止めた録音の音と形式。"""

    samples: np.ndarray
    """モノラルの 16 bit の音。"""

    sample_rate: int
    """サンプルレート（Hz）。"""

    duration_sec: float
    """録音の長さ（一時停止の間を除く）。"""
