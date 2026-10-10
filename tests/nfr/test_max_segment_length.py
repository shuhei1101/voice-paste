"""区間の最大の長さ（max_segment_length）の非機能要件テスト。

Windows の音声合成（SAPI）で、文の間を区切る無音の長さより短くして 45 秒以上読み上げ続けた WAV を作り、
区切りの部品（Segmenter・本物の話し声の判定）に、録音の入力と同じ大きさの塊で流して、切り出した区間の長さを測る。
文字起こしと実機のマイクは使わない。SAPI が使えない環境では skip する。
"""

from __future__ import annotations

import sys
from itertools import cycle
from pathlib import Path

import numpy as np
import pytest

from tests.support.inprocess import long_reading_texts, speech_sequence_input
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.recording.segmenter import MAX_SEGMENT_SEC, Segmenter
from voice_paste.integrations.vad.adapter import StreamingVad, load_vad_session
from voice_paste.shared.settings import ContinuousSettings
from voice_paste.shared.types import Segment

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows の音声合成（SAPI）が要る"
)

SENTENCE_GAP_SEC = 0.4
"""文と文の間に挟む無音の長さ。区切る無音の長さの既定（2 秒）より十分に短い。"""

MIN_READING_SEC = 45.0
"""読み上げ続ける長さの下限（区間の最大の長さの 1.5 倍）。"""

CHUNK_FRAMES_CYCLE = (160, 1024, 480, 800)
"""録音の入力が 1 回に渡すフレーム数（160〜1024）。この並びを繰り返して流す。"""


def _feed_in_chunks(segmenter: Segmenter, samples: np.ndarray) -> None:
    """samples を CHUNK_FRAMES_CYCLE の大きさの塊に分けて、最後まで Segmenter へ渡す。"""
    position = 0
    for size in cycle(CHUNK_FRAMES_CYCLE):
        # 全ての音を渡し終えたら終わる
        if position >= len(samples):
            return
        segmenter.feed(samples[position : position + size])
        position += size


def test_max_segment_length(tmp_path: Path) -> None:
    """話し続けた録音から切り出した区間が、どれも決定値以下の長さである。"""
    # 準備: 文の間を 0.5 秒以下にして 45 秒以上読み上げ続けた WAV を作り、区切りの部品を本物の話し声の判定で組む
    samples = speech_sequence_input(
        tmp_path, long_reading_texts(), gap_sec=SENTENCE_GAP_SEC
    ).samples
    assert len(samples) / SAMPLE_RATE >= MIN_READING_SEC
    segments: list[Segment] = []
    segmenter = Segmenter(
        detect_speech=StreamingVad(load_vad_session()),
        on_segment=segments.append,
        min_silence_sec=ContinuousSettings().min_silence_sec,
    )

    # 実行
    _feed_in_chunks(segmenter, samples)
    segmenter.flush()

    # 検証
    durations = [segment.recording.duration_sec for segment in segments]
    print(  # noqa: T201 測った値を実行の出力に残す
        f"max_segment_length: reading={len(samples) / SAMPLE_RATE:.1f}s "
        f"segments={[f'{duration:.2f}s' for duration in durations]}"
    )
    assert len(durations) >= 2
    assert max(durations) <= MAX_SEGMENT_SEC
