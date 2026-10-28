"""音量を変えない実装。Linux で lower_volume・restore_volume の代わりに渡す。"""

from __future__ import annotations

NOOP_VOLUME: float = 1.0
"""lower_volume_noop が下げる前の音量として返す値。音量を読まないため最大の 1.0 を置く。"""


def lower_volume_noop(ratio: float, fade_sec: float) -> float:
    """音量を読まず変えず、NOOP_VOLUME を返す（restore_volume_noop にだけ渡り、捨てられる）。"""
    return NOOP_VOLUME


def restore_volume_noop(volume: float, fade_sec: float) -> None:
    """何もしない。"""
