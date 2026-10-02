"""features/recording/client.py（open_input）の単体テスト。

sounddevice.InputStream は、作られ方を記録してコールバックを呼べる偽物に差し替える。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

FRAME_COUNT = 160
SAMPLE_RATE = 16000


class FakeInputStream:
    """sounddevice.InputStream の偽物。作られたときの引数と start の呼び出しを覚える。"""

    instances: list[FakeInputStream] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.started = False
        FakeInputStream.instances.append(self)

    def start(self) -> None:
        """入力を始めたことを覚える。"""
        self.started = True

    def deliver(self, indata: np.ndarray) -> None:
        """入力のスレッドの代わりに、渡されたコールバックへ音を届ける。"""
        callback: Callable[..., None] = self.kwargs["callback"]
        callback(indata, len(indata), None, None)


@pytest.fixture
def fake_streams(monkeypatch: pytest.MonkeyPatch) -> list[FakeInputStream]:
    """sounddevice.InputStream を偽物に差し替え、作られた偽物の一覧を返す。"""
    FakeInputStream.instances = []
    monkeypatch.setattr("sounddevice.InputStream", FakeInputStream)
    return FakeInputStream.instances


def test_open_input(fake_streams: list[FakeInputStream]) -> None:
    """決めた形式で開いて始め、届いた音を渡す（正常系）。"""
    from voice_paste.features.recording.client import open_input

    # 準備
    received: list[np.ndarray] = []
    indata = np.arange(FRAME_COUNT, dtype=np.int16).reshape(FRAME_COUNT, 1)
    expected = indata.copy()

    # 実行
    stream = open_input(received.append)
    fake_streams[0].deliver(indata)
    # コールバックが返った後に入力の側が同じバッファを書き換えても、渡した音は変わらない
    indata[:] = 0

    # 検証
    assert stream is fake_streams[0]
    assert fake_streams[0].kwargs["samplerate"] == SAMPLE_RATE
    assert fake_streams[0].kwargs["channels"] == 1
    assert fake_streams[0].kwargs["dtype"] == "int16"
    assert fake_streams[0].started
    assert np.array_equal(received[0], expected)
