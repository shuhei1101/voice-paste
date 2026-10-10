"""features/recording/segmenter.py（Segmenter の feed・flush）の単体テスト。

話し声の判定は、窓ごとの確率を決めた並びで返す偽物に差し替える（1 窓 = 512 サンプル = 32 ms）。
音は 16 kHz の int16 で、判定の呼び出しの順と窓が 1 対 1 になるよう、窓の数で長さを決めて作る。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from tests.unit.voice_paste.features.recording.helpers import (
    ScriptedDetector,
    SegmentSink,
    all_values,
    feed_all,
    phases_audio,
    shared_values,
    speech_window_values,
    windows,
)

if TYPE_CHECKING:
    from voice_paste.features.recording.segmenter import Segmenter

WINDOW_SAMPLES = 512
# 話し声の前に残す余白（0.3 秒）のサンプル数
PAD_SAMPLES = 4800
# 前の余白（0.3 秒）+ 話し声 1 秒 + 後ろの余白（0.3 秒）のサンプル数
SILENCE_CUT_SAMPLES = 25600
# 20 秒と 20.2 秒の位置（サンプル数）
PAUSE_START_SAMPLES = 320000
PAUSE_END_SAMPLES = 323200
# 区間の最大の長さ（30 秒）のサンプル数
MAX_SEGMENT_SAMPLES = 480000
# 1 秒の話し声（31 窓）に、窓に満たない末尾の 100 サンプルを足したサンプル数
SPEECH_AND_TAIL_SAMPLES = 15972


def _make_segmenter(
    detector: ScriptedDetector, sink: SegmentSink, *, min_silence_sec: float
) -> Segmenter:
    """偽物の判定と区間の渡し先で Segmenter を作る。"""
    from voice_paste.features.recording.segmenter import Segmenter

    return Segmenter(detect_speech=detector, on_segment=sink, min_silence_sec=min_silence_sec)


# === feed ===


def test_feed_cuts_at_silence() -> None:
    """話し声の後の無音が区切る長さに達したら区切る（正常系）。"""
    # 準備: 0.5 秒の無音、1 秒の話し声、2.5 秒の無音（区切る長さは 2 秒）
    phases = [(0.0, windows(0.5)), (0.9, windows(1.0)), (0.0, windows(2.5))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証: 長さは「前の余白 + 話し声 1 秒 + 後ろの余白」に 1 窓（512 サンプル）の誤差で合う
    assert sink.reasons() == ["silence"]
    length = sink.segments[0].recording.samples.size
    assert length == pytest.approx(SILENCE_CUT_SAMPLES, abs=WINDOW_SAMPLES)


def test_feed_keeps_short_pause() -> None:
    """区切る長さに届かない無音では区切らない（正常系）。"""
    # 準備: 1 秒の話し声、1 秒の無音、1 秒の話し声（区切る長さは 2 秒）
    phases = [(0.9, windows(1.0)), (0.0, windows(1.0)), (0.9, windows(1.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証
    assert sink.segments == []


def test_feed_cuts_at_max_length() -> None:
    """無音が来ないまま最大の長さに達したら、直近の短い無音の中で区切る（正常系）。"""
    # 準備: 話し声が続く中、20 秒の位置に 0.2 秒の短い無音を挟み、最大の長さ（30 秒）を超える 32 秒を流す
    phases = [(0.9, windows(20.0)), (0.2, windows(0.2)), (0.9, windows(11.8))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証: 区間の終わり（先頭からのサンプル数）が 20 秒〜20.2 秒の無音の中にある
    assert sink.reasons() == ["max_length"]
    length = sink.segments[0].recording.samples.size
    assert PAUSE_START_SAMPLES <= length <= PAUSE_END_SAMPLES


def test_feed_cuts_at_max_length_without_pause() -> None:
    """短い無音も無ければ最大の長さの位置で区切る（正常系）。"""
    # 準備: 常に話し声と判定し、最大の長さ（30 秒）より 1 秒長く流す
    phases = [(0.9, windows(31.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証
    assert sink.reasons() == ["max_length"]
    length = sink.segments[0].recording.samples.size
    assert length <= MAX_SEGMENT_SAMPLES
    assert length == pytest.approx(MAX_SEGMENT_SAMPLES, abs=WINDOW_SAMPLES)


def test_feed_ignores_silence_only() -> None:
    """話し声を含まない間は区間にしない（正常系）。"""
    # 準備: 常に無音と判定し、10 秒流す
    phases = [(0.0, windows(10.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証
    assert sink.segments == []


def test_feed_does_not_drop_samples() -> None:
    """区間をつなぐと話し声が落ちていない（正常系）。"""
    # 準備: 話し声と区切る無音（0.5 秒）を 3 回繰り返す。音は窓ごとに連番の値を入れる
    phases = [
        (0.0, 8),
        (0.9, 20),
        (0.0, 24),
        (0.0, 8),
        (0.9, 20),
        (0.0, 24),
        (0.0, 8),
        (0.9, 20),
        (0.0, 24),
    ]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=0.5)

    # 実行
    feed_all(segmenter, phases_audio(phases, numbered=True))
    segmenter.flush()

    # 検証
    assert len(sink.segments) == 3
    assert speech_window_values(phases) <= all_values(sink.segments)
    assert shared_values(sink.segments) == set()


def test_feed_trims_audio_when_silence_only() -> None:
    """話し声を含まない間は、貯める音を余白 + 窓 1〜2 つ分に収める（正常系）。"""
    # 準備: 常に無音と判定し、60 秒流す
    phases = [(0.0, windows(60.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証
    assert segmenter._audio.size <= PAD_SAMPLES + 2 * WINDOW_SAMPLES
    assert sink.segments == []


def test_feed_trims_audio_when_silent_after_cut() -> None:
    """無音で区切った後に無音が続いても、貯める音を余白 + 窓 1〜2 つ分に収める（正常系）。"""
    # 準備: 1 秒の話し声の後に、区切る長さ（2 秒）を超えて 59 秒の無音を流す
    phases = [(0.9, windows(1.0)), (0.0, windows(59.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases))

    # 検証
    assert sink.reasons() == ["silence"]
    assert segmenter._audio.size <= PAD_SAMPLES + 2 * WINDOW_SAMPLES


def test_feed_keeps_head_pad_after_trim() -> None:
    """無音を長く流した後の話し声でも、話し声の前の余白まで区間に含める（正常系）。"""
    # 準備: 30 秒の無音、1 秒の話し声、2.5 秒の無音（区切る長さは 2 秒）。音は窓ごとに連番の値を入れる
    phases = [(0.0, windows(30.0)), (0.9, windows(1.0)), (0.0, windows(2.5))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)

    # 実行
    feed_all(segmenter, phases_audio(phases, numbered=True))

    # 検証: 前の余白 + 話し声 1 秒 + 後ろの余白に 1 窓の誤差で合い、話し声の窓が全て含まれる
    assert sink.reasons() == ["silence"]
    length = sink.segments[0].recording.samples.size
    assert length == pytest.approx(SILENCE_CUT_SAMPLES, abs=WINDOW_SAMPLES)
    assert speech_window_values(phases) <= all_values(sink.segments)


# === flush ===


def test_flush_when_speaking() -> None:
    """話し声の途中なら最後の区間を渡す（正常系）。"""
    # 準備: 1 秒の話し声の後に、窓に満たない 100 サンプル（値 9999）を流す
    phases = [(0.9, windows(1.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)
    tail = np.full(100, 9999, dtype=np.int16)
    feed_all(segmenter, np.concatenate([phases_audio(phases, numbered=True), tail]))

    # 実行
    segmenter.flush()

    # 検証: 末尾の 100 サンプルまで含む
    assert sink.reasons() == ["flush"]
    samples = sink.segments[0].recording.samples
    assert samples.size == SPEECH_AND_TAIL_SAMPLES
    assert (samples[-100:] == 9999).all()


def test_flush_when_silent_after_speech() -> None:
    """話し終えて区切る長さに届く前の無音で止めても、その文を区間にする（正常系）。"""
    # 準備: 1 秒の話し声の後に 1 秒の無音を流す（区切る長さは 2 秒）
    phases = [(0.9, windows(1.0)), (0.0, windows(1.0))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)
    feed_all(segmenter, phases_audio(phases))

    # 実行
    segmenter.flush()

    # 検証
    assert sink.reasons() == ["flush"]


def test_flush_when_idle() -> None:
    """話し声が残っていなければ何も渡さない（正常系）。"""
    # 準備: 話し声の後の無音で区切った直後にする
    phases = [(0.9, windows(1.0)), (0.0, windows(2.5))]
    sink = SegmentSink()
    segmenter = _make_segmenter(ScriptedDetector(phases), sink, min_silence_sec=2.0)
    feed_all(segmenter, phases_audio(phases))

    # 実行
    segmenter.flush()

    # 検証: 区切りで渡した 1 つだけで、flush では増えない
    assert sink.reasons() == ["silence"]
