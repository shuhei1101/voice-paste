"""haas_server/audio.py（decode_audio）の単体テスト。"""

from __future__ import annotations

import io
import wave
from fractions import Fraction

import av
import numpy as np
import pytest

SECONDS = 1
SOURCE_RATE = 48000
TARGET_RATE = 16000
TOLERANCE_SAMPLES = 1600


def _stereo_wav() -> bytes:
    """約 1 秒の 48 kHz・2 チャンネルの WAV のバイト列を作る。"""
    frames = np.zeros(SOURCE_RATE * SECONDS * 2, dtype=np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(SOURCE_RATE)
        writer.writeframes(frames.tobytes())
    return buffer.getvalue()


def _webm() -> bytes:
    """約 1 秒の webm（Opus）のバイト列を PyAV で作る。"""
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="webm") as container:
        stream = container.add_stream("libopus", rate=SOURCE_RATE)
        samples = np.zeros((1, SOURCE_RATE * SECONDS), dtype=np.int16)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = SOURCE_RATE
        frame.time_base = Fraction(1, SOURCE_RATE)
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


def test_decode_audio() -> None:
    """48 kHz のステレオの WAV を 16 kHz のモノラルにする（正常系）。"""
    from haas_server.audio import decode_audio

    # 実行
    samples = decode_audio(_stereo_wav())

    # 検証
    assert samples.ndim == 1
    assert samples.dtype == np.float32
    assert abs(len(samples) - TARGET_RATE) < TOLERANCE_SAMPLES


def test_decode_audio_when_webm() -> None:
    """webm（Opus）を復号できる（正常系）。"""
    from haas_server.audio import decode_audio

    # 実行
    samples = decode_audio(_webm())

    # 検証
    assert abs(len(samples) - TARGET_RATE) < TOLERANCE_SAMPLES


def test_decode_audio_when_not_audio() -> None:
    """音声でないバイト列は AudioDecodeError を送出する（異常系）。"""
    from haas_server.audio import AudioDecodeError, decode_audio

    # 実行・検証
    with pytest.raises(AudioDecodeError):
        decode_audio(b"not audio")
