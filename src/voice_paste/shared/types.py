"""feature の間を渡る型。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

type ProgressFn = Callable[[float, float], None]
"""文字起こしの区間の終わりの時刻と録音の長さ（秒）を知らせる関数。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording:
    """止めた録音の音と形式。"""

    samples: np.ndarray
    """モノラルの 16 bit の音。"""

    sample_rate: int
    """サンプルレート（Hz）。"""

    duration_sec: float
    """録音の長さ（一時停止の間を除く）。"""
