"""Haas の文字起こしのサーバーの結合テストの共通の部品。"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import av
import numpy as np

from haas_server.app import HaasEngine

MODEL_NAME = "third-intelligence/Haas-ja-v1.0"
FAKE_TEXT = "請求データと入金データを月末に突合します。"
SOURCE_RATE = 48000
MODEL_RATE = 16000
TOLERANCE_SAMPLES = 1600


@dataclass
class FakeModel:
    """Haas のモデルの代わり。受けた音声と Vocabulary を記録し、決まった文字を返す。"""

    samples: list[np.ndarray] = field(default_factory=list)
    vocabularies: list[Any] = field(default_factory=list)
    longform_calls: int = 0
    errors: list[Exception] = field(default_factory=list)

    def transcribe(self, samples: np.ndarray, vocabulary: Any | None) -> str:
        """音声と Vocabulary を記録し、決まった文字を返す。errors があれば先頭を送出する。"""
        self.samples.append(samples)
        self.vocabularies.append(vocabulary)
        if self.errors:
            raise self.errors.pop(0)
        return FAKE_TEXT

    def transcribe_longform(self, samples: np.ndarray, vocabulary: Any | None) -> str:
        """30 秒を超える音声の起こし方。呼ばれた回数を数える。"""
        self.longform_calls += 1
        return self.transcribe(samples, vocabulary)

    def engine(self) -> HaasEngine:
        """このモデルの関数を束ねる。Vocabulary は受けた対応をそのまま返す。"""
        return HaasEngine(
            model_name=MODEL_NAME,
            transcribe=self.transcribe,
            transcribe_longform=self.transcribe_longform,
            build_vocabulary=lambda words: words,
        )


def make_wav(seconds: float) -> bytes:
    """16 bit・モノラル・48 kHz の無音の WAV のバイト列を作る。"""
    frames = np.zeros(int(SOURCE_RATE * seconds), dtype=np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SOURCE_RATE)
        writer.writeframes(frames.tobytes())
    return buffer.getvalue()


def make_webm(seconds: float) -> bytes:
    """webm（Opus）の無音のバイト列を PyAV で作る。"""
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="webm") as container:
        stream = container.add_stream("libopus", rate=SOURCE_RATE)
        samples = np.zeros((1, int(SOURCE_RATE * seconds)), dtype=np.int16)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = SOURCE_RATE
        frame.time_base = Fraction(1, SOURCE_RATE)
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()
