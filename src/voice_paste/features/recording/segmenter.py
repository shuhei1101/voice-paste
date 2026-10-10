"""窓ごとの話し声の確率から、録音を止めずに区間を切り出す。"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.recording.types import SpeechProbabilityFn
from voice_paste.shared.types import OnSegmentFn, Recording, Segment

logger = logging.getLogger(__name__)

VAD_WINDOW: int = 512
"""話し声の判定に 1 回で渡すサンプル数（16 kHz で 32 ms。Silero VAD が受ける窓の大きさ）。"""

SPEECH_THRESHOLD: float = 0.5
"""話し声と判定する確率（faster-whisper の VadOptions の既定と同じ）。"""

NEG_THRESHOLD: float = 0.35
"""話し声の終わり（無音の候補）と判定する確率（SPEECH_THRESHOLD − 0.15。faster-whisper の既定の決め方と同じ）。"""

SHORT_SILENCE_SEC: float = 0.098
"""最大の長さで区切るときに区切りの候補にする無音の長さ（秒。faster-whisper の get_speech_timestamps の最大の長さの区切りと同じ）。"""

SEGMENT_PAD_SEC: float = 0.3
"""話し声の前後に残す余白（秒。言葉の頭と尾を切らないため）。"""

MAX_SEGMENT_SEC: float = 30.0
"""無音が来ないままこの長さ（秒）に達したら区切る。非機能要件の区間の最大の長さの決定値。"""

INT16_SCALE: float = 32768.0
"""入力の int16 の音を話し声の判定が受ける -1.0〜1.0 の float32 にする除数。"""

type SegmentReason = Literal["silence", "max_length", "flush"]
"""区間を区切った理由。"""


class Segmenter:
    """届いた音を VAD_WINDOW サンプルの窓に組み直し、窓ごとの話し声の確率から区間を切り出して区切った順に渡す。

    窓をまたいで区切りの状態（話し声の始まり・無音の候補・前の区切り）と、前の区切り以降の音を持ち続けるためクラスにする。
    区切ったら区切りより前の音を手放し、持つ音は区間の最大の長さ程度に収める。
    区切りのスレッドからだけ呼ぶ（並行で呼ばない）。
    """

    def __init__(
        self,
        *,
        detect_speech: SpeechProbabilityFn,
        on_segment: OnSegmentFn,
        min_silence_sec: float,
    ) -> None:
        """話し声の判定・区間の渡し先・区切る無音の長さ（秒）を受ける。"""
        self._detect_speech = detect_speech
        self._on_segment = on_segment
        self._min_silence_samples = int(min_silence_sec * SAMPLE_RATE)
        self._pad_samples = int(SEGMENT_PAD_SEC * SAMPLE_RATE)
        self._max_samples = int(MAX_SEGMENT_SEC * SAMPLE_RATE)
        self._short_silence_samples = int(SHORT_SILENCE_SEC * SAMPLE_RATE)
        # 前の区切り以降の音（int16）と、その先頭が録音の始めから何サンプル目か
        self._audio = np.zeros(0, dtype=np.int16)
        self._audio_start = 0
        # 窓に満たない末尾の音（float32）
        self._pending = np.zeros(0, dtype=np.float32)
        # 判定し終えたサンプル数
        self._position = 0
        # 話し声の途中か、今の区間の話し声の始まり、続いている無音の始まり（無ければ 0）
        self._triggered = False
        self._speech_start = 0
        self._temp_end = 0
        # 直近の短い無音の中ほど（最大の長さで区切るときの候補。無ければ 0）と、前の区切りの位置
        self._last_short_silence = 0
        self._previous_cut = 0

    def feed(self, block: np.ndarray) -> None:
        """届いた音（int16）を貯め、1 窓ずつ話し声の確率を求めて区切りの状態を進める。"""
        # 1. 1 次元にして、前の区切り以降の音と、窓に組み直す音に足す
        samples = np.asarray(block).reshape(-1)
        self._audio = np.concatenate([self._audio, samples.astype(np.int16)])
        self._pending = np.concatenate([self._pending, samples.astype(np.float32) / INT16_SCALE])

        # 2. 窓に満たなくなるまで、先頭の 1 窓ずつ判定して状態を進める
        while self._pending.size >= VAD_WINDOW:
            window = self._pending[:VAD_WINDOW]
            self._pending = self._pending[VAD_WINDOW:]
            self._step(self._detect_speech(window))
            self._position += VAD_WINDOW

    def flush(self) -> None:
        """話し声の途中なら、そこまでを最後の区間として渡す（窓に満たない末尾の音も含める）。"""
        if not self._triggered:
            return
        self._emit(self._audio_start + self._audio.size, "flush")
        self._triggered = False

    def _step(self, probability: float) -> None:
        """1 窓の確率で区切りの状態を進め、区切りが決まれば区間を渡す。"""
        position = self._position

        # 1. 話し声なら無音の候補を取り消し、話し声の途中でなければここを話し声の始まりにする
        if probability >= SPEECH_THRESHOLD:
            self._temp_end = 0
            if not self._triggered:
                self._triggered = True
                self._speech_start = position
                self._last_short_silence = 0

        # 2. 話し声の途中でなければ何もしない
        if not self._triggered:
            return

        # 3. この窓を含めると最大の長さを超えるなら、直近の短い無音の中か今の位置で区切り、そこを次の話し声の始まりにする
        if position + VAD_WINDOW - self._speech_start > self._max_samples:
            has_short_silence = self._last_short_silence > self._speech_start
            cut = self._last_short_silence if has_short_silence else position
            self._emit(cut, "max_length")
            self._speech_start = cut
            self._last_short_silence = 0
            self._temp_end = 0
            return

        # 4. 無音の候補として続いた長さを数える
        if probability < NEG_THRESHOLD:
            if not self._temp_end:
                self._temp_end = position
            silence_samples = position + VAD_WINDOW - self._temp_end
            # 短い無音に達したら、その中ほどを最大の長さで区切るときの候補として控える
            if silence_samples >= self._short_silence_samples:
                self._last_short_silence = self._temp_end + silence_samples // 2
            # 区切る無音の長さに達したら、無音の始まりの余白の後ろで区切る
            if silence_samples >= self._min_silence_samples:
                self._emit(self._temp_end + self._pad_samples, "silence")
                self._triggered = False
                self._temp_end = 0
                self._last_short_silence = 0

    def _emit(self, cut: int, reason: SegmentReason) -> None:
        """前の区切り（か話し声の始まり − 余白の遅い方）から cut までを区間にして渡し、cut より前の音を手放す。"""
        # 1. 区間の始まりを決め、貯めた音から切り出す
        start = max(self._previous_cut, self._speech_start - self._pad_samples)
        samples = self._audio[start - self._audio_start : cut - self._audio_start].copy()
        recording = Recording(
            samples=samples, sample_rate=SAMPLE_RATE, duration_sec=samples.size / SAMPLE_RATE
        )

        # 2. 区間を渡す
        logger.info(f"区間を区切った（{reason}・{recording.duration_sec:.1f} 秒）")
        self._on_segment(Segment(recording=recording, reason=reason))

        # 3. cut を前の区切りにして、それより前の音を手放す
        self._previous_cut = cut
        self._audio = self._audio[cut - self._audio_start :]
        self._audio_start = cut
