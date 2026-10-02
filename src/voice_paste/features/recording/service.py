"""録音の開始・一時停止・再開・停止・破棄と、録音中の音の大きさ。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from voice_paste.features.recording.client import DTYPE, SAMPLE_RATE
from voice_paste.features.recording.types import LowerVolumeFn, OpenInputFn, RestoreVolumeFn
from voice_paste.shared.errors import MicrophoneUnavailableError, VolumeControlError
from voice_paste.shared.settings import RecordingSettings
from voice_paste.shared.types import Recording

logger = logging.getLogger(__name__)

PERCENT_DIVISOR: float = 100.0
"""設定の音量の割合（0〜100）を、音量の関数へ渡す割合（0.0〜1.0）にする除数。"""

INT16_MAX: int = int(np.iinfo(np.int16).max)
"""int16 の最大値。音の大きさ（RMS）を 0.0〜1.0 にする分母。"""


class Recorder:
    """開いているマイクの入力と貯めた音、下げる前の音量を持つ録音機。"""

    def __init__(
        self,
        *,
        lower_volume: LowerVolumeFn,
        restore_volume: RestoreVolumeFn,
        open_input: OpenInputFn,
        get_settings: Callable[[], RecordingSettings],
    ) -> None:
        """音量を下げる・戻す関数、マイクの入力を開く関数、今の録音の設定を返す関数を受ける。"""
        self._lower_volume = lower_volume
        self._restore_volume = restore_volume
        self._open_input = open_input
        self._get_settings = get_settings
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._paused = False
        self._latest_frame: np.ndarray | None = None
        # 下げる前の音量。下げていなければ None
        self._volume_before: float | None = None
        # 始めたときに読んだ、音量を変えるときの秒数（戻すときも同じ値を使う）
        self._fade_sec = 0.0
        # 入力のスレッドと呼び出し元のスレッドの間で、貯めた音と状態を守る
        self._lock = threading.Lock()

    def start(self) -> None:
        """音量を下げてマイクを開く。開けなければ音量を戻して MicrophoneUnavailableError を送出する。"""
        # 1. 録音中なら断る（呼び出し順の誤り。セッションが排他する）
        if self._stream is not None:
            raise RuntimeError("すでに録音中です")

        # 2. 設定を読み直し、貯めた音・一時停止・直近の音を空に戻す
        settings = self._get_settings()
        with self._lock:
            self._frames = []
            self._paused = False
            self._latest_frame = None
            self._fade_sec = settings.fade_sec

        # 3. 設定が音量を下げるなら下げ、下げる前の音量を持つ
        if settings.lower_volume:
            try:
                self._volume_before = self._lower_volume(
                    settings.volume_percent / PERCENT_DIVISOR, settings.fade_sec
                )
            except VolumeControlError as error:
                # 音量を操作できなくても録音は止めない
                logger.warning(f"音量を下げられなかった（{error}）")

        # 4. マイクの入力を開く。開けなければ下げた音量を戻す
        try:
            self._stream = self._open_input(self._on_frames)
        except Exception as error:  # noqa: BLE001 sounddevice が送出する例外の型は決まっていない
            logger.exception(f"マイクを開けなかった（{error}）")
            self._restore_volume_once()
            raise MicrophoneUnavailableError(f"マイクを開けませんでした: {error}") from error
        logger.info(f"録音を始めた（音量を下げた: {self._volume_before is not None}）")

    def pause(self) -> None:
        """入力は開いたまま、音を貯めるのを止める。録音していなければ何もしない。"""
        with self._lock:
            if self._stream is None:
                return
            self._paused = True
            self._latest_frame = None

    def resume(self) -> None:
        """音を貯めるのを再び始める。録音していなければ何もしない。"""
        with self._lock:
            if self._stream is None:
                return
            self._paused = False

    def stop(self) -> Recording:
        """入力を閉じ、音量を戻し、貯めた音を返す。録音していなければ RuntimeError を送出する。"""
        # 1. 録音していなければ断る（呼び出し順の誤り）
        if self._stream is None:
            raise RuntimeError("録音していません")

        # 2. 入力を閉じて音量を戻す（閉じた後は音が届かない）
        self._close()

        # 3. 貯めた音をつないで Recording にする。音が無ければ長さ 0 の音にする
        with self._lock:
            frames = self._frames
            self._frames = []
        if frames:
            samples = np.concatenate(frames).reshape(-1)
        else:
            samples = np.zeros(0, dtype=DTYPE)
        recording = Recording(
            samples=samples, sample_rate=SAMPLE_RATE, duration_sec=samples.size / SAMPLE_RATE
        )
        logger.info(f"録音を止めた（{recording.duration_sec:.1f} 秒）")
        return recording

    def discard(self) -> None:
        """入力を閉じ、音量を戻し、貯めた音を捨てる。録音していなければ何もしない。"""
        if self._stream is None:
            return
        self._close()
        with self._lock:
            self._frames = []
        logger.info("録音を捨てた")

    def level(self) -> float:
        """直近に届いた音の RMS を int16 の最大で割り、0.0〜1.0 で返す。届いていなければ 0.0 を返す。"""
        with self._lock:
            frame = self._latest_frame
            # 録音していない・一時停止中・音が届いていない場合は 0
            if self._stream is None or self._paused or frame is None:
                return 0.0
        rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))))
        return min(rms / INT16_MAX, 1.0)

    def _on_frames(self, frames: np.ndarray) -> None:
        """入力のスレッドから呼ばれ、一時停止中でなければ届いた音を貯める。"""
        with self._lock:
            if self._paused:
                return
            self._frames.append(frames)
            self._latest_frame = frames

    def _close(self) -> None:
        """入力を止めて閉じ、下げた音量があれば戻す。"""
        # 1. 入力を止めて閉じる。ロックは持たない（止めるときに入力のスレッドの終わりを待つため）
        stream = self._stream
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as error:  # noqa: BLE001 sounddevice が送出する例外の型は決まっていない
                # 閉じられなくても閉じたものとして続ける
                logger.warning(f"マイクの入力を閉じられなかった（{error}）")
        with self._lock:
            self._stream = None
            self._latest_frame = None

        # 2. 下げた音量があれば戻す
        self._restore_volume_once()

    def _restore_volume_once(self) -> None:
        """下げる前の音量があれば戻し、持っていた音量を捨てる（戻すのは 1 回だけ）。"""
        if self._volume_before is None:
            return
        volume = self._volume_before
        self._volume_before = None
        try:
            self._restore_volume(volume, self._fade_sec)
        except VolumeControlError as error:
            logger.warning(f"音量を戻せなかった（{error}）")
