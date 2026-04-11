"""マイク録音・WAVファイル保存モジュール。"""

from pathlib import Path

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

from voice_paste.constants import SAMPLE_RATE, DEFAULT_AUDIO_TMP
from voice_paste.exceptions import RecordingError
from voice_paste.logger import get_logger

logger = get_logger(__name__)


class AudioRecorder:
    """マイク録音を管理するクラス。"""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        """
        AudioRecorder を初期化する。

        :param sample_rate: サンプリングレート（Hz）
        """
        self._sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        # 波形表示用の最新フレームバッファ
        self._latest_frame: np.ndarray = np.zeros(1, dtype="int16")

    def get_level(self) -> float:
        """
        現在の録音レベルをRMS（0.0〜1.0）で返す。

        :return: 正規化された音量レベル（0.0〜1.0）
        """
        rms = float(np.sqrt(np.mean(self._latest_frame.astype("float32") ** 2)))
        # int16の最大値（32767）で正規化
        return min(rms / 32767.0, 1.0)

    def start(self) -> None:
        """録音を開始する。"""
        logger.info("Recording started. sample_rate=%d", self._sample_rate)
        self._frames = []
        self._latest_frame = np.zeros(1, dtype="int16")

        def callback(indata: np.ndarray, frames: int, time: object, status: object) -> None:
            # 録音データをバッファに追加し、最新フレームを更新
            if status:
                logger.warning("Recording status: %s", status)
            self._frames.append(indata.copy())
            self._latest_frame = indata.copy()

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=callback,
        )
        self._stream.start()

    def stop_and_save(self, output_path: Path = DEFAULT_AUDIO_TMP) -> Path:
        """
        録音を停止し、WAVファイルとして保存する。

        :param output_path: 保存先パス
        :return: 保存されたWAVファイルのパス
        :raises RecordingError: 録音データが存在しない場合
        """
        if self._stream is None:
            raise RecordingError("Recording has not been started.")

        self._stream.stop()
        self._stream.close()
        self._stream = None
        logger.info("Recording stopped.")

        if not self._frames:
            raise RecordingError("No audio data recorded.")

        # フレームを結合してWAVファイルに保存
        audio_data = np.concatenate(self._frames, axis=0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav.write(str(output_path), self._sample_rate, audio_data)
        logger.info("Audio saved: path=%s, frames=%d", output_path, len(audio_data))
        return output_path

    def cancel(self) -> None:
        """録音をキャンセルする（ファイル保存なし）。"""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._frames = []
        logger.info("Recording cancelled.")
