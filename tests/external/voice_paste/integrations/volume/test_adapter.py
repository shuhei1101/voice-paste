"""integrations/volume/adapter.py（lower_volume・restore_volume）の契約テスト。

Windows の実機の既定の再生デバイスで pycaw を動かし、pycaw の版が上がって API が変わったことに気づけるようにする。
実行中はシステム音量が変わり、終わりに実行前の音量へ戻す。既定の再生デバイスが無い環境では skip する。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import comtypes
import pytest

VOLUME_BEFORE = 0.6
LOWERED_VOLUME = 0.3
VOLUME_TOLERANCE = 0.01
FADE_SEC = 0.3
FADE_DEADLINE_SEC = 2.0
POLL_SEC = 0.05


class MasterVolume:
    """pycaw で直接マスター音量を読み書きする（被テスト側の関数を通さない確認用）。"""

    def __init__(self) -> None:
        from pycaw.pycaw import AudioUtilities

        self._endpoint = AudioUtilities.GetSpeakers().EndpointVolume

    def get(self) -> float:
        """今のマスター音量（0.0〜1.0）を読む。"""
        return float(self._endpoint.GetMasterVolumeLevelScalar())

    def set(self, volume: float) -> None:
        """マスター音量を書く。"""
        self._endpoint.SetMasterVolumeLevelScalar(volume, None)


@pytest.fixture
def master_volume() -> Iterator[MasterVolume]:
    """実機のマスター音量を読み書きする窓口を返し、テストの後に実行前の音量へ戻す。"""
    from voice_paste.integrations.volume.adapter import restore_volume

    comtypes.CoInitialize()
    try:
        try:
            master = MasterVolume()
            original = master.get()
        except Exception as error:  # noqa: BLE001 既定の再生デバイスが無い環境の例外の型は決まっていない
            pytest.skip(f"既定の再生デバイスの音量を読めないため skip する（{error}）")
        yield master
        # 進行中のフェードを打ち切ってから、実行前の音量へ戻す
        restore_volume(original, 0)
        master.set(original)
    finally:
        comtypes.CoUninitialize()


def test_ext_lower_volume_when_no_fade(master_volume: MasterVolume) -> None:
    """実機の既定の再生デバイスで、下げる前の音量を返して割合を掛けた音量へ変える（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume

    # 準備
    master_volume.set(VOLUME_BEFORE)

    # 実行
    before = lower_volume(0.5, 0)

    # 検証
    assert before == pytest.approx(VOLUME_BEFORE, abs=VOLUME_TOLERANCE)
    assert master_volume.get() == pytest.approx(LOWERED_VOLUME, abs=VOLUME_TOLERANCE)


def test_ext_lower_volume_when_fade(master_volume: MasterVolume) -> None:
    """フェードをかけても割合を掛けた音量に届く（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume

    # 準備
    master_volume.set(VOLUME_BEFORE)

    # 実行
    before = lower_volume(0.5, FADE_SEC)
    deadline = time.monotonic() + FADE_DEADLINE_SEC
    # 目標の音量に届くまで（上限まで）待つ
    while (
        time.monotonic() < deadline
        and abs(master_volume.get() - LOWERED_VOLUME) > VOLUME_TOLERANCE
    ):
        time.sleep(POLL_SEC)

    # 検証
    assert before == pytest.approx(VOLUME_BEFORE, abs=VOLUME_TOLERANCE)
    assert master_volume.get() == pytest.approx(LOWERED_VOLUME, abs=VOLUME_TOLERANCE)


def test_ext_restore_volume_when_no_fade(master_volume: MasterVolume) -> None:
    """実機の既定の再生デバイスで、下げた音量を戻す（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume, restore_volume

    # 準備
    master_volume.set(VOLUME_BEFORE)
    lower_volume(0.5, 0)

    # 実行
    restore_volume(VOLUME_BEFORE, 0)

    # 検証
    assert master_volume.get() == pytest.approx(VOLUME_BEFORE, abs=VOLUME_TOLERANCE)
