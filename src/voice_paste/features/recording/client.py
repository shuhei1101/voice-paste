"""sounddevice でマイクの入力を開く。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE: int = 16000
"""マイクの入力のサンプルレート（Hz）。"""

CHANNELS: int = 1
"""マイクの入力のチャンネル数（モノラル）。"""

DTYPE: str = "int16"
"""マイクの入力の型（16 bit の整数）。"""


def open_input(on_frames: Callable[[np.ndarray], None]) -> sd.InputStream:
    """既定の入力デバイスを 16 kHz・モノラル・int16 のコールバックのストリームで開いて始める。"""

    def _callback(
        indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags
    ) -> None:
        """入力のスレッドから呼ばれ、届いた音の写しを渡す。"""
        if status:
            logger.warning(f"入力の状態（{status}）")
        # indata は次のコールバックで使い回されるため、写しを渡す
        on_frames(indata.copy())

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, callback=_callback
    )
    stream.start()
    return stream
