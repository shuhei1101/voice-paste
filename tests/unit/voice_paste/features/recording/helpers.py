"""features/recording の単体テスト用の偽物と音の組み立て。

話し声の判定は「窓ごとの確率を決めた並びで返す」偽物に、区間の渡し先は「渡された区間を覚える」偽物に差し替える。
音は、窓の数で長さを決めた int16 の配列で作る（1 窓 = VAD_WINDOW サンプル）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from voice_paste.features.recording.segmenter import Segmenter
    from voice_paste.features.recording.service import Recorder
    from voice_paste.shared.types import Segment

SAMPLE_RATE = 16000
VAD_WINDOW = 512
SPEECH_THRESHOLD = 0.5
BLOCK_FRAMES = 1024
SEGMENTER_THREAD_NAME = "recording-segmenter"
WAIT_SEC = 3.0
POLL_SEC = 0.01

type Phases = Sequence[tuple[float, int]]
"""(話し声の確率, 窓の数) の並び。先頭から順に、その確率の窓が続く。"""


def windows(seconds: float) -> int:
    """seconds 秒に当たる判定の窓の数（四捨五入）を返す。"""
    return round(seconds * SAMPLE_RATE / VAD_WINDOW)


class ScriptedDetector:
    """窓ごとの話し声の確率を決めた並びで返す、話し声の判定の偽物。並びを使い切ったら tail を返す。"""

    def __init__(
        self,
        phases: Phases,
        *,
        tail: float = 0.0,
        fail_on_call: int | None = None,
        error: Exception | None = None,
    ) -> None:
        """phases の並びと使い切った後の確率を受ける。fail_on_call 回目（1 始まり）の呼び出しでは error を送出する。"""
        self._probabilities = [
            probability for probability, count in phases for _ in range(count)
        ]
        self._tail = tail
        self._fail_on_call = fail_on_call
        self._error = error
        self.calls = 0

    def __call__(self, window: np.ndarray) -> float:
        """次の窓の確率を返す（失敗の指定があれば、その回に送出する）。"""
        self.calls += 1
        if self._error is not None and self.calls == self._fail_on_call:
            raise self._error
        index = self.calls - 1
        return self._probabilities[index] if index < len(self._probabilities) else self._tail


class SegmentSink:
    """区間の渡し先の偽物。渡された区間を渡された順に覚え、届いたら arrived を立てる。"""

    def __init__(self) -> None:
        """空の状態で作る。"""
        self.segments: list[Segment] = []
        self.arrived = threading.Event()

    def __call__(self, segment: Segment) -> None:
        """区間を覚える。"""
        self.segments.append(segment)
        self.arrived.set()

    def reasons(self) -> list[str]:
        """渡された区間の区切った理由を、渡された順に返す。"""
        return [segment.reason for segment in self.segments]


class FailureSink:
    """連続録音の失敗の知らせ先の偽物。渡された理由を覚え、届いたら arrived を立てる。"""

    def __init__(self) -> None:
        """空の状態で作る。"""
        self.reasons: list[str] = []
        self.arrived = threading.Event()

    def __call__(self, reason: str) -> None:
        """理由を覚える。"""
        self.reasons.append(reason)
        self.arrived.set()


def phases_audio(phases: Phases, *, numbered: bool = False) -> np.ndarray:
    """phases の窓の数だけの音（int16・1 次元）を作る。numbered なら k 番目の窓（0 始まり）を値 k + 1 で埋める。"""
    total = sum(count for _, count in phases)
    if numbered:
        return np.repeat(np.arange(1, total + 1, dtype=np.int16), VAD_WINDOW)
    return np.zeros(total * VAD_WINDOW, dtype=np.int16)


def feed_all(segmenter: Segmenter, audio: np.ndarray) -> None:
    """audio を BLOCK_FRAMES ずつ（最後は短く）、入力と同じ構造 (フレーム数, 1) にして Segmenter へ流す。"""
    for start in range(0, audio.size, BLOCK_FRAMES):
        segmenter.feed(audio[start : start + BLOCK_FRAMES].reshape(-1, 1))


def window_values(segment: Segment) -> set[int]:
    """区間の音に含まれる 0 以外の値（numbered の音では、含まれる窓の番号）の集合を返す。"""
    return {int(value) for value in np.unique(segment.recording.samples) if value != 0}


def speech_window_values(phases: Phases) -> set[int]:
    """phases のうち話し声の窓（確率が閾値以上）に、numbered の音が入れた値の集合を返す。"""
    values: set[int] = set()
    index = 0
    for probability, count in phases:
        if probability >= SPEECH_THRESHOLD:
            values.update(range(index + 1, index + count + 1))
        index += count
    return values


def all_values(segments: Sequence[Segment]) -> set[int]:
    """区間のどれかに含まれる値の集合を返す。"""
    values: set[int] = set()
    for segment in segments:
        values |= window_values(segment)
    return values


def shared_values(segments: Sequence[Segment]) -> set[int]:
    """2 つ以上の区間に含まれる値の集合を返す（区間が重なっていなければ空）。"""
    seen: set[int] = set()
    shared: set[int] = set()
    for segment in segments:
        values = window_values(segment)
        shared |= seen & values
        seen |= values
    return shared


def segmenter_threads_gone(timeout: float = WAIT_SEC) -> bool:
    """区切りのスレッドが残っていないことを、timeout 秒まで待って確かめる。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(
            thread.name == SEGMENTER_THREAD_NAME and thread.is_alive()
            for thread in threading.enumerate()
        ):
            return True
        time.sleep(POLL_SEC)
    return False


def queued_blocks(recorder: Recorder) -> int:
    """録音が区切りのスレッドへ渡す待ち行列に残っている音の数を返す（待ち行列が無ければ 0）。"""
    blocks = recorder._blocks
    return 0 if blocks is None else blocks.qsize()
