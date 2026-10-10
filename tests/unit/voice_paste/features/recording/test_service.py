"""features/recording/service.py（Recorder の start・pause・resume・stop・discard・level・start_continuous・stop_continuous）の単体テスト。

音量の操作・マイクの入力を開く関数・設定を返す関数・話し声の判定を作る関数は、呼び出しを記録する偽物に差し替える。
マイクの入力は、入力のスレッドの代わりにテストが on_frames へ音を流す。
連続録音の区切りのスレッドは本物を動かし、区間や失敗の知らせが届くのを待って確かめる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pytest

from tests.unit.voice_paste.features.recording.helpers import (
    WAIT_SEC,
    FailureSink,
    ScriptedDetector,
    SegmentSink,
    queued_blocks,
    segmenter_threads_gone,
    windows,
)
from voice_paste.shared.errors import MicrophoneUnavailableError, VolumeControlError
from voice_paste.shared.settings import RecordingSettings

if TYPE_CHECKING:
    from voice_paste.features.recording.service import Recorder

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1
VOLUME_BEFORE = 0.8
FADE_SEC = 0.5
MIN_SILENCE_SEC = 0.5


class FakeStream:
    """sounddevice.InputStream の偽物。stop・close の呼び出しを覚える。"""

    def __init__(self, on_frames: Callable[[np.ndarray], None]) -> None:
        self.on_frames = on_frames
        self.stop_calls = 0
        self.close_calls = 0

    def stop(self) -> None:
        """入力を止めたことを覚える。"""
        self.stop_calls += 1

    def close(self) -> None:
        """入力を閉じたことを覚える。"""
        self.close_calls += 1


@dataclass
class Harness:
    """Recorder と、注入した偽物が覚えた呼び出し。"""

    recorder: Recorder = field(init=False)
    events: list[str] = field(default_factory=list)
    lower_calls: list[tuple[float, float]] = field(default_factory=list)
    restore_calls: list[tuple[float, float]] = field(default_factory=list)
    streams: list[FakeStream] = field(default_factory=list)
    lower_error: Exception | None = None
    restore_error: Exception | None = None
    open_error: Exception | None = None
    # 連続録音を始めるたびに呼ばれ、新しい話し声の判定を返す（既定は常に無音と判定する）
    detector_factory: Callable[[], Callable[[np.ndarray], float]] = field(
        default=lambda: ScriptedDetector([])
    )

    def feed(self, seconds: float) -> None:
        """今開いている入力へ、無音を seconds 秒分（0.1 秒ずつ）流す。"""
        chunk = np.zeros((int(SAMPLE_RATE * CHUNK_SEC), 1), dtype=np.int16)
        for _ in range(round(seconds / CHUNK_SEC)):
            self.streams[-1].on_frames(chunk)

    def feed_square(self, amplitude: int) -> None:
        """今開いている入力へ、振幅 amplitude の矩形の音を 0.1 秒分流す。"""
        frames = int(SAMPLE_RATE * CHUNK_SEC)
        signs = np.where(np.arange(frames) % 2 == 0, 1, -1)
        self.streams[-1].on_frames((signs * amplitude).astype(np.int16).reshape(frames, 1))


@pytest.fixture
def harness_factory() -> Iterator[Callable[..., Harness]]:
    """偽物を注入した Recorder と、その呼び出しの記録を作る関数を返す。作った録音機はテストの後に捨てる（区切りのスレッドを残さない）。"""
    created: list[Harness] = []

    def _create(
        *,
        lower_volume: bool = True,
        volume_percent: float = 50,
        fade_sec: float = FADE_SEC,
    ) -> Harness:
        from voice_paste.features.recording.service import Recorder

        settings = RecordingSettings(
            lower_volume=lower_volume, volume_percent=volume_percent, fade_sec=fade_sec
        )
        harness = Harness()

        def fake_lower_volume(ratio: float, fade: float) -> float:
            harness.events.append("lower_volume")
            harness.lower_calls.append((ratio, fade))
            if harness.lower_error is not None:
                raise harness.lower_error
            return VOLUME_BEFORE

        def fake_restore_volume(volume: float, fade: float) -> None:
            harness.events.append("restore_volume")
            harness.restore_calls.append((volume, fade))
            if harness.restore_error is not None:
                raise harness.restore_error

        def fake_open_input(on_frames: Callable[[np.ndarray], None]) -> FakeStream:
            harness.events.append("open_input")
            if harness.open_error is not None:
                raise harness.open_error
            stream = FakeStream(on_frames)
            harness.streams.append(stream)
            return stream

        harness.recorder = Recorder(
            lower_volume=fake_lower_volume,
            restore_volume=fake_restore_volume,
            open_input=fake_open_input,
            get_settings=lambda: settings,
            create_speech_detector=lambda: harness.detector_factory(),
        )
        created.append(harness)
        return harness

    yield _create

    for harness in created:
        harness.recorder.discard()


# === start ===


def test_start(harness_factory: Callable[..., Harness]) -> None:
    """音量を下げてマイクを開く（正常系）。"""
    # 準備
    harness = harness_factory(lower_volume=True, volume_percent=50, fade_sec=0.5)

    # 実行
    harness.recorder.start()

    # 検証
    assert harness.lower_calls == [(0.5, 0.5)]
    assert harness.events == ["lower_volume", "open_input"]


def test_start_when_lower_volume_disabled(harness_factory: Callable[..., Harness]) -> None:
    """音量を下げない設定なら音量に触れない（正常系）。"""
    # 準備
    harness = harness_factory(lower_volume=False)

    # 実行
    harness.recorder.start()

    # 検証
    assert harness.events == ["open_input"]


def test_start_when_microphone_unavailable(harness_factory: Callable[..., Harness]) -> None:
    """マイクを開けなければ音量を戻す（異常系）。"""
    # 準備
    harness = harness_factory()
    opening_error = OSError("マイクが無い")
    harness.open_error = opening_error

    # 実行・検証
    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        harness.recorder.start()
    assert exc_info.value.__cause__ is opening_error
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]

    # 失敗の後に続けて始められる
    harness.open_error = None
    harness.recorder.start()
    assert len(harness.streams) == 1


def test_start_when_volume_control_failed(harness_factory: Callable[..., Harness]) -> None:
    """音量を下げられなくても録音は始める（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.lower_error = VolumeControlError("音量を読めない")

    # 実行
    harness.recorder.start()
    harness.recorder.stop()

    # 検証
    assert len(harness.streams) == 1
    assert harness.restore_calls == []


def test_start_when_already_recording(harness_factory: Callable[..., Harness]) -> None:
    """録音中の開始は断る（異常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()

    # 実行・検証
    with pytest.raises(RuntimeError):
        harness.recorder.start()
    assert harness.events == ["lower_volume", "open_input"]


# === pause ===


def test_pause_when_not_recording(harness_factory: Callable[..., Harness]) -> None:
    """録音していなければ何もしない（正常系）。"""
    # 準備
    harness = harness_factory()

    # 実行
    harness.recorder.pause()

    # 検証（続く start が通る）
    harness.recorder.start()
    assert len(harness.streams) == 1


# === stop ===


def test_stop(harness_factory: Callable[..., Harness]) -> None:
    """貯めた音を返して音量を戻す（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed(1.0)

    # 実行
    recording = harness.recorder.stop()

    # 検証
    assert recording.duration_sec == pytest.approx(1.0)
    assert recording.sample_rate == SAMPLE_RATE
    assert recording.samples.dtype == np.int16
    assert recording.samples.size == SAMPLE_RATE
    assert harness.streams[0].stop_calls == 1
    assert harness.streams[0].close_calls == 1
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]


def test_stop_when_paused_between(harness_factory: Callable[..., Harness]) -> None:
    """一時停止の間の音は貯めない（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed(1.0)
    harness.recorder.pause()
    harness.feed(1.0)
    harness.recorder.resume()
    harness.feed(1.0)

    # 実行
    recording = harness.recorder.stop()

    # 検証
    assert recording.duration_sec == pytest.approx(2.0)


def test_stop_when_no_frames(harness_factory: Callable[..., Harness]) -> None:
    """音が届く前に止めたら長さ 0 の音を返す（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()

    # 実行
    recording = harness.recorder.stop()

    # 検証
    assert recording.duration_sec == 0.0
    assert recording.samples.size == 0


def test_stop_when_restore_failed(harness_factory: Callable[..., Harness]) -> None:
    """音量を戻せなくても録音は返す（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed(1.0)
    harness.restore_error = VolumeControlError("音量を戻せない")

    # 実行
    recording = harness.recorder.stop()

    # 検証
    assert recording.duration_sec == pytest.approx(1.0)


def test_stop_when_not_recording(harness_factory: Callable[..., Harness]) -> None:
    """録音していなければ断る（異常系）。"""
    # 準備
    harness = harness_factory()

    # 実行・検証
    with pytest.raises(RuntimeError):
        harness.recorder.stop()


# === discard ===


def test_discard(harness_factory: Callable[..., Harness]) -> None:
    """音を捨てて音量を戻す（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed(1.0)

    # 実行
    harness.recorder.discard()
    harness.recorder.start()
    recording = harness.recorder.stop()

    # 検証
    assert harness.restore_calls[0] == (VOLUME_BEFORE, FADE_SEC)
    assert recording.duration_sec == 0.0


def test_discard_when_not_recording(harness_factory: Callable[..., Harness]) -> None:
    """録音していなければ何もしない（正常系）。"""
    # 準備
    harness = harness_factory()

    # 実行
    harness.recorder.discard()

    # 検証
    assert harness.restore_calls == []


def test_discard_when_continuous(harness_factory: Callable[..., Harness]) -> None:
    """連続録音を捨てると残りの音を区間にしない（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.detector_factory = lambda: ScriptedDetector([], tail=0.9)
    sink = SegmentSink()
    harness.recorder.start_continuous(sink, MagicMock(), min_silence_sec=MIN_SILENCE_SEC)
    harness.feed(1.0)

    # 実行
    harness.recorder.discard()

    # 検証
    assert sink.segments == []
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]
    assert segmenter_threads_gone()
    harness.recorder.start()
    assert len(harness.streams) == 2


# === level ===


def test_level(harness_factory: Callable[..., Harness]) -> None:
    """直近の音の大きさを返す（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed_square(16384)

    # 実行
    level = harness.recorder.level()

    # 検証
    assert level == pytest.approx(0.5, abs=0.01)


def test_level_when_paused(harness_factory: Callable[..., Harness]) -> None:
    """一時停止中は 0（正常系）。"""
    # 準備
    harness = harness_factory()
    harness.recorder.start()
    harness.feed_square(16384)
    harness.recorder.pause()

    # 実行
    level = harness.recorder.level()

    # 検証
    assert level == 0.0


# === start_continuous ===


def test_start_continuous(harness_factory: Callable[..., Harness]) -> None:
    """届いた音が区切りへ流れ、区間が on_segment へ渡る（正常系）。"""
    # 準備: 最初の 1 秒だけ話し声と判定し、その後は無音と判定する
    harness = harness_factory()
    harness.detector_factory = lambda: ScriptedDetector([(0.9, windows(1.0))])
    sink = SegmentSink()

    # 実行
    harness.recorder.start_continuous(sink, MagicMock(), min_silence_sec=MIN_SILENCE_SEC)
    harness.feed(2.0)
    arrived = sink.arrived.wait(timeout=WAIT_SEC)

    # 検証
    assert arrived
    assert sink.reasons() == ["silence"]
    assert harness.lower_calls == [(0.5, FADE_SEC)]
    assert harness.streams[0].stop_calls == 0
    assert harness.streams[0].close_calls == 0


def test_start_continuous_when_microphone_unavailable(
    harness_factory: Callable[..., Harness],
) -> None:
    """マイクを開けなければ区切りのスレッドを止めて音量を戻す（異常系）。"""
    # 準備
    harness = harness_factory()
    harness.open_error = OSError("マイクが無い")
    sink = SegmentSink()

    # 実行・検証
    with pytest.raises(MicrophoneUnavailableError, match="マイク"):
        harness.recorder.start_continuous(sink, MagicMock(), min_silence_sec=MIN_SILENCE_SEC)
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]
    assert sink.segments == []
    assert segmenter_threads_gone()


def test_start_continuous_when_segmenter_failed(harness_factory: Callable[..., Harness]) -> None:
    """区切りに失敗したら入力を閉じて音量を戻し、on_failed に知らせる（異常系）。"""
    # 準備: 3 窓目の判定で例外を送出する
    harness = harness_factory()
    harness.detector_factory = lambda: ScriptedDetector(
        [], fail_on_call=3, error=RuntimeError("VAD が落ちた")
    )
    failures = FailureSink()
    harness.recorder.start_continuous(MagicMock(), failures, min_silence_sec=MIN_SILENCE_SEC)

    # 実行
    harness.feed(1.0)
    notified = failures.arrived.wait(timeout=WAIT_SEC)
    harness.feed(1.0)

    # 検証
    assert notified
    assert len(failures.reasons) == 1
    assert "VAD が落ちた" in failures.reasons[0]
    assert harness.streams[0].stop_calls == 1
    assert harness.streams[0].close_calls == 1
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]
    assert queued_blocks(harness.recorder) == 0
    harness.recorder.start()
    assert len(harness.streams) == 2


# === stop_continuous ===


def test_stop_continuous(harness_factory: Callable[..., Harness]) -> None:
    """話し声の途中で止めると、残りを最後の区間として渡してから戻る（正常系）。"""
    # 準備: 常に話し声と判定する
    harness = harness_factory()
    harness.detector_factory = lambda: ScriptedDetector([], tail=0.9)
    sink = SegmentSink()
    harness.recorder.start_continuous(sink, MagicMock(), min_silence_sec=MIN_SILENCE_SEC)
    harness.feed(1.0)

    # 実行
    harness.recorder.stop_continuous()

    # 検証
    assert sink.reasons() == ["flush"]
    assert harness.streams[0].stop_calls == 1
    assert harness.streams[0].close_calls == 1
    assert harness.restore_calls == [(VOLUME_BEFORE, FADE_SEC)]
    harness.recorder.start()
    assert len(harness.streams) == 2


def test_stop_continuous_when_no_speech(harness_factory: Callable[..., Harness]) -> None:
    """話し声が無ければ区間を渡さない（正常系）。"""
    # 準備: 常に無音と判定する
    harness = harness_factory()
    harness.detector_factory = lambda: ScriptedDetector([], tail=0.0)
    sink = SegmentSink()
    harness.recorder.start_continuous(sink, MagicMock(), min_silence_sec=MIN_SILENCE_SEC)
    harness.feed(2.0)

    # 実行
    harness.recorder.stop_continuous()

    # 検証
    assert sink.segments == []


def test_stop_continuous_when_not_recording(harness_factory: Callable[..., Harness]) -> None:
    """連続録音していなければ断る（異常系）。"""
    # 準備: 連続でない録音を始める
    harness = harness_factory()
    harness.recorder.start()

    # 実行・検証
    with pytest.raises(RuntimeError, match="連続録音"):
        harness.recorder.stop_continuous()
