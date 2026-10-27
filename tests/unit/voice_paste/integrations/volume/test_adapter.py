"""integrations/volume/adapter.py（lower_volume・restore_volume・_fade_to・_cancel_fade）の単体テスト。

pycaw の音量のインターフェースは、音量を持って書き込みを記録する偽物に差し替える（_open_endpoint_volume を差し替える）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from comtypes import COMError

FADE_WAIT_SEC = 1.0
SETTLE_SEC = 0.3
POLL_SEC = 0.01


class FakeEndpointVolume:
    """IAudioEndpointVolume の偽物。マスター音量を持ち、書き込まれた値を順に覚える。"""

    def __init__(self, volume: float) -> None:
        self.volume = volume
        self.writes: list[float] = []
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None
        self._lock = threading.Lock()

    def GetMasterVolumeLevelScalar(self) -> float:  # noqa: N802 pycaw の名前に合わせる
        """今のマスター音量（0.0〜1.0）を返す。read_error があれば送出する。"""
        if self.read_error is not None:
            raise self.read_error
        return self.volume

    def SetMasterVolumeLevelScalar(self, level: float, context: Any) -> None:  # noqa: N802 pycaw の名前に合わせる
        """マスター音量を書き、書いた値を覚える。write_error があれば送出する。"""
        if self.write_error is not None:
            raise self.write_error
        with self._lock:
            self.volume = level
            self.writes.append(level)


@pytest.fixture
def install_endpoint(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], FakeEndpointVolume]:
    """音量を持つ偽のインターフェースを _open_endpoint_volume の返り値にする関数を返す。"""

    def _install(volume: float) -> FakeEndpointVolume:
        endpoint = FakeEndpointVolume(volume)
        monkeypatch.setattr(
            "voice_paste.integrations.volume.adapter._open_endpoint_volume", lambda: endpoint
        )
        return endpoint

    return _install


def _is_non_increasing(values: list[float]) -> bool:
    """values が前から後ろへ増えずに並んでいるか。"""
    return all(earlier >= later for earlier, later in zip(values, values[1:], strict=False))


def _run_no_fade(adapter: ModuleType) -> None:
    """フェードを始めない。"""


def _run_finished_fade(adapter: ModuleType) -> None:
    """短いフェードを始め、終わるまで待つ。"""
    adapter._fade_to(0.4, 0.05)
    time.sleep(FADE_WAIT_SEC)


# === lower_volume ===


def test_lower_volume(install_endpoint: Callable[[float], FakeEndpointVolume]) -> None:
    """今の音量を返し、割合を掛けた音量へ書く（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume

    # 準備
    endpoint = install_endpoint(0.8)

    # 実行
    before = lower_volume(0.5, 0)

    # 検証
    assert before == pytest.approx(0.8)
    assert endpoint.volume == pytest.approx(0.4)


def test_lower_volume_when_restoring(
    install_endpoint: Callable[[float], FakeEndpointVolume],
) -> None:
    """戻している途中に下げると、戻しの目標の音量を下げる前の音量にする（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume, restore_volume

    # 準備
    endpoint = install_endpoint(0.4)
    restore_volume(0.8, 0.5)

    # 実行
    before = lower_volume(0.5, 0)
    writes_after_lowering = len(endpoint.writes)
    time.sleep(FADE_WAIT_SEC)

    # 検証
    assert before == pytest.approx(0.8)
    assert endpoint.volume == pytest.approx(0.4)
    assert len(endpoint.writes) == writes_after_lowering


def test_lower_volume_when_read_failed(
    install_endpoint: Callable[[float], FakeEndpointVolume],
) -> None:
    """読めなければ VolumeControlError（異常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume
    from voice_paste.shared.errors import VolumeControlError

    # 準備
    endpoint = install_endpoint(0.8)
    reading_error = COMError(-2147467259, "読めない", (None, None, None, 0, None))
    endpoint.read_error = reading_error

    # 実行・検証
    with pytest.raises(VolumeControlError) as exc_info:
        lower_volume(0.5, 0)
    assert exc_info.value.__cause__ is reading_error
    assert endpoint.writes == []


def test_lower_volume_when_api_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """pycaw の API が変わって属性が無ければ VolumeControlError（異常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume
    from voice_paste.shared.errors import VolumeControlError

    # 準備
    def _removed_api() -> FakeEndpointVolume:
        raise AttributeError("EndpointVolume")

    monkeypatch.setattr(
        "voice_paste.integrations.volume.adapter._open_endpoint_volume", _removed_api
    )

    # 実行・検証
    with pytest.raises(VolumeControlError):
        lower_volume(0.5, 0)


# === restore_volume ===


def test_restore_volume_when_lowering(
    install_endpoint: Callable[[float], FakeEndpointVolume],
) -> None:
    """下げている途中でも戻す音量で終わる（正常系）。"""
    from voice_paste.integrations.volume.adapter import lower_volume, restore_volume

    # 準備
    endpoint = install_endpoint(0.8)
    lower_volume(0.5, 0.5)

    # 実行
    restore_volume(0.8, 0.1)
    time.sleep(FADE_WAIT_SEC)
    writes_after_restoring = len(endpoint.writes)
    time.sleep(SETTLE_SEC)

    # 検証
    assert endpoint.volume == pytest.approx(0.8)
    assert len(endpoint.writes) == writes_after_restoring


# === _fade_to ===


def test_fade_to(install_endpoint: Callable[[float], FakeEndpointVolume]) -> None:
    """FADE_STEPS 回で目標の音量に届く（正常系）。"""
    from voice_paste.integrations.volume import adapter

    # 準備
    endpoint = install_endpoint(0.8)

    # 実行
    adapter._fade_to(0.4, 0.1)
    time.sleep(FADE_WAIT_SEC)

    # 検証
    assert len(endpoint.writes) == adapter.FADE_STEPS
    assert _is_non_increasing(endpoint.writes)
    assert endpoint.writes[-1] == pytest.approx(0.4)


def test_fade_to_when_write_failed(
    install_endpoint: Callable[[float], FakeEndpointVolume],
) -> None:
    """すぐ変えるときに書けなければ VolumeControlError（異常系）。"""
    from voice_paste.integrations.volume.adapter import _fade_to
    from voice_paste.shared.errors import VolumeControlError

    # 準備
    endpoint = install_endpoint(0.8)
    endpoint.write_error = COMError(-2147467259, "書けない", (None, None, None, 0, None))

    # 実行・検証
    with pytest.raises(VolumeControlError):
        _fade_to(0.4, 0)


# === _cancel_fade ===


@pytest.mark.parametrize(
    "prepare",
    [
        pytest.param(_run_no_fade, id="never_started"),
        pytest.param(_run_finished_fade, id="finished"),
    ],
)
def test_cancel_fade_when_idle(
    install_endpoint: Callable[[float], FakeEndpointVolume],
    prepare: Callable[[ModuleType], None],
) -> None:
    """進行中のフェードが無ければ None（正常系）。"""
    from voice_paste.integrations.volume import adapter

    # 準備
    install_endpoint(0.8)
    prepare(adapter)

    # 実行
    target = adapter._cancel_fade()

    # 検証
    assert target is None
