"""integrations/volume/noop.py（lower_volume_noop）の単体テスト。

音量を読まず変えない実装のため、Mock は使わない。
"""

from __future__ import annotations

RATIO = 0.5
FADE_SEC = 0.5


def test_lower_volume_noop() -> None:
    """音量を変えずに決まった値を返す（正常系）。"""
    from voice_paste.integrations.volume.noop import NOOP_VOLUME, lower_volume_noop

    # 実行
    volume = lower_volume_noop(RATIO, FADE_SEC)

    # 検証
    assert volume == NOOP_VOLUME
