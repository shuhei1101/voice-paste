"""録音の開始・一時停止・再開・停止・破棄と、録音中の音の大きさ。連続録音では録音を止めずに区間を区切る。"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from voice_paste.features.recording.client import DTYPE, SAMPLE_RATE
from voice_paste.features.recording.segmenter import Segmenter
from voice_paste.features.recording.types import (
    CreateSpeechDetectorFn,
    LowerVolumeFn,
    OpenInputFn,
    RestoreVolumeFn,
)
from voice_paste.shared.errors import MicrophoneUnavailableError, VolumeControlError
from voice_paste.shared.settings import RecordingSettings
from voice_paste.shared.types import OnContinuousFailedFn, OnSegmentFn, Recording

logger = logging.getLogger(__name__)

PERCENT_DIVISOR: float = 100.0
"""設定の音量の割合（0〜100）を、音量の関数へ渡す割合（0.0〜1.0）にする除数。"""

INT16_MAX: int = int(np.iinfo(np.int16).max)
"""int16 の最大値。音の大きさ（RMS）を 0.0〜1.0 にする分母。"""

SEGMENT_THREAD_NAME: str = "recording-segmenter"
"""連続録音で、待ち行列の音を Segmenter へ流すスレッドの名前。"""

_DISCARD_MARK: np.ndarray = np.zeros(0, dtype=np.int16)
"""待ち行列に積む、残りを区間にせずにスレッドを終えるマーカー（None は残りを区切って終えるマーカー。中身ではなく同じ物かで比べる）。"""


class Recorder:
    """開いているマイクの入力と貯めた音、下げる前の音量を持つ録音機。"""

    def __init__(
        self,
        *,
        lower_volume: LowerVolumeFn,
        restore_volume: RestoreVolumeFn,
        open_input: OpenInputFn,
        get_settings: Callable[[], RecordingSettings],
        create_speech_detector: CreateSpeechDetectorFn,
    ) -> None:
        """音量を下げる・戻す関数、マイクの入力を開く関数、今の録音の設定を返す関数、連続録音用の話し声の判定を作る関数を受ける。"""
        self._lower_volume = lower_volume
        self._restore_volume = restore_volume
        self._open_input = open_input
        self._get_settings = get_settings
        self._create_speech_detector = create_speech_detector
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._paused = False
        self._latest_frame: np.ndarray | None = None
        # 下げる前の音量。下げていなければ None
        self._volume_before: float | None = None
        # 始めたときに読んだ、音量を変えるときの秒数（戻すときも同じ値を使う）
        self._fade_sec = 0.0
        # 連続録音で、入力のスレッドから区切りのスレッドへ渡す音の待ち行列（None は残りを区切って終えるマーカー）と、そのスレッド。連続録音でなければ None
        self._blocks: queue.Queue[np.ndarray | None] | None = None
        self._segment_thread: threading.Thread | None = None
        # 入力のスレッドと呼び出し元のスレッドの間で、貯めた音と状態を守る
        self._lock = threading.Lock()

    def start(self) -> None:
        """音量を下げてマイクを開く。開けなければ音量を戻して MicrophoneUnavailableError を送出する。"""
        # 1. 録音中なら断る（呼び出し順の誤り。セッションが排他する）
        if self._stream is not None:
            raise RuntimeError("すでに録音中です")

        # 2〜3. 設定を読み直して貯めた音を空に戻し、設定が音量を下げるなら下げる
        self._prepare_recording()

        # 4. マイクの入力を開く。開けなければ下げた音量を戻す
        try:
            self._stream = self._open_input(self._on_frames)
        except Exception as error:  # noqa: BLE001 sounddevice が送出する例外の型は決まっていない
            logger.exception(f"マイクを開けなかった（{error}）")
            self._restore_volume_once()
            raise MicrophoneUnavailableError(f"マイクを開けませんでした: {error}") from error
        logger.info(f"録音を始めた（音量を下げた: {self._volume_before is not None}）")

    def start_continuous(
        self,
        on_segment: OnSegmentFn,
        on_failed: OnContinuousFailedFn,
        *,
        min_silence_sec: float,
    ) -> None:
        """音量を下げてマイクを開き、届いた音を区切りのスレッドで Segmenter へ流す。区切った区間は on_segment へ渡る。"""
        # 1. 録音中なら断る（呼び出し順の誤り。セッションが排他する）
        if self._stream is not None:
            raise RuntimeError("すでに録音中です")

        # 2. 設定を読み直し、設定が音量を下げるなら下げる
        self._prepare_recording()

        # 3. 新しい話し声の判定で Segmenter を作り、区切りのスレッドを始める
        segmenter = Segmenter(
            detect_speech=self._create_speech_detector(),
            on_segment=on_segment,
            min_silence_sec=min_silence_sec,
        )
        blocks: queue.Queue[np.ndarray | None] = queue.Queue()
        thread = threading.Thread(
            target=self._run_segmenter,
            args=(segmenter, blocks, on_failed),
            name=SEGMENT_THREAD_NAME,
            daemon=True,
        )
        with self._lock:
            self._blocks = blocks
            self._segment_thread = thread
        thread.start()

        # 4. マイクの入力を開く。開けなければ区切りのスレッドを flush せずに止め、下げた音量を戻す
        try:
            self._stream = self._open_input(self._on_frames)
        except Exception as error:  # noqa: BLE001 sounddevice が送出する例外の型は決まっていない
            logger.exception(f"マイクを開けなかった（{error}）")
            self._stop_segment_thread(flush=False)
            self._restore_volume_once()
            raise MicrophoneUnavailableError(f"マイクを開けませんでした: {error}") from error
        logger.info(
            f"連続録音を始めた（区切る無音: {min_silence_sec} 秒・音量を下げた: {self._volume_before is not None}）"
        )

    def stop_continuous(self) -> None:
        """入力を閉じて音量を戻し、待ち行列に残った音を区切り終えてから、区間に切り出していない話し声を最後の区間として渡す。"""
        # 1. 連続録音していなければ断る（呼び出し順の誤り。区切りに失敗して自ら止めた後を含む）
        with self._lock:
            continuous = self._blocks is not None
        if self._stream is None or not continuous:
            raise RuntimeError("連続録音していません")

        # 2. 入力を閉じて音量を戻す（閉じた後は音が届かない）
        self._close()

        # 3. 待ち行列に残った音を区切り終え、最後の区間まで渡し終えるのを待つ
        self._stop_segment_thread(flush=True)
        logger.info("連続録音を止めた")

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
        # 連続録音なら、区切りのスレッドを残りの音を区間にせずに止める
        self._stop_segment_thread(flush=False)
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
            # 連続録音は貯めず、区切りのスレッドへ渡すだけにする（入力のコールバックを遅らせない）
            if self._blocks is not None:
                self._blocks.put(frames)
                return
            if self._paused:
                return
            self._frames.append(frames)
            self._latest_frame = frames

    def _prepare_recording(self) -> None:
        """設定を読み直し、貯めた音・一時停止・直近の音を空に戻して、設定が音量を下げるなら下げる。"""
        # 1. 設定を読み直し、貯めた音・一時停止・直近の音を空に戻す
        settings = self._get_settings()
        with self._lock:
            self._frames = []
            self._paused = False
            self._latest_frame = None
            self._fade_sec = settings.fade_sec

        # 2. 設定が音量を下げるなら下げ、下げる前の音量を持つ
        if settings.lower_volume:
            try:
                self._volume_before = self._lower_volume(
                    settings.volume_percent / PERCENT_DIVISOR, settings.fade_sec
                )
            except VolumeControlError as error:
                # 音量を操作できなくても録音は止めない
                logger.warning(f"音量を下げられなかった（{error}）")

    def _run_segmenter(
        self,
        segmenter: Segmenter,
        blocks: queue.Queue[np.ndarray | None],
        on_failed: OnContinuousFailedFn,
    ) -> None:
        """区切りのスレッドの本体。待ち行列の音を Segmenter へ流し、終わりのマーカーで残りを区切って終える。"""
        try:
            while True:
                block = blocks.get()
                # 捨てるマーカー: 残りを区間にせずに終える
                if block is _DISCARD_MARK:
                    return
                # 終わりのマーカー: 話し声の途中なら最後の区間を渡して終える
                if block is None:
                    segmenter.flush()
                    return
                segmenter.feed(block)
        except Exception as error:  # noqa: BLE001 区切りの失敗はどの例外でも録音を止めて知らせる
            logger.exception("連続録音の区切りに失敗したため録音を止めた")
            self._abort_continuous(blocks)
            on_failed(str(error))

    def _abort_continuous(self, blocks: queue.Queue[np.ndarray | None]) -> None:
        """区切りに失敗した連続録音を終える。入力を閉じて音量を戻し、待ち行列を空にする。それまでに渡した区間はそのまま。"""
        # 待ち行列とスレッドを手放し、入力が音を積めないようにする
        with self._lock:
            self._blocks = None
            self._segment_thread = None
        self._close()
        while not blocks.empty():
            blocks.get_nowait()

    def _stop_segment_thread(self, *, flush: bool) -> None:
        """区切りのスレッドの終わりを待ち、待ち行列とスレッドを手放す。flush なら残りを区切ってから、そうでなければ残りを区間にせずに終える。"""
        with self._lock:
            blocks = self._blocks
            thread = self._segment_thread
            self._blocks = None
            self._segment_thread = None
        if blocks is None or thread is None:
            return

        # 残りを区間にしないなら待ち行列の音を捨ててから、終わりのマーカーを積む
        if not flush:
            while not blocks.empty():
                blocks.get_nowait()
        blocks.put(None if flush else _DISCARD_MARK)
        thread.join()

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
