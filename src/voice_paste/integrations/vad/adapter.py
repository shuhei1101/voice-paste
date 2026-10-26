"""faster-whisper 同梱の Silero VAD を onnxruntime で窓ごとに流す。onnxruntime の API に触れるのはこのファイルだけ。"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from voice_paste.shared.errors import StartupError

logger = logging.getLogger(__name__)

VAD_CONTEXT: int = 64
"""Silero VAD が前の窓から持ち越す文脈のサンプル数（faster-whisper の context_size_samples と同じ）。"""

VAD_STATE_SHAPE: tuple[int, int, int] = (1, 1, 128)
"""Silero VAD の LSTM の状態 h・c の形状。"""

VAD_MODEL_RELATIVE_PATH: str = "assets/silero_vad_v6.onnx"
"""faster-whisper のパッケージからの Silero VAD のモデルの置き場所（faster-whisper 1.2.1 の get_vad_model が開くものと同じ）。"""

ORT_LOG_SEVERITY_FATAL: int = 4
"""onnxruntime のログを致命的なものだけにする水準。"""


def load_vad_session() -> ort.InferenceSession:
    """faster-whisper 同梱の Silero VAD を、faster_whisper を import せずに onnxruntime の CPU で開いて返す。"""
    # 1. find_spec でパッケージの場所だけを引く（faster_whisper の __init__ は ctranslate2 と CUDA の DLL を読むため実行しない）
    spec = importlib.util.find_spec("faster_whisper")
    if spec is None or not spec.submodule_search_locations:
        logger.error("VAD を読めなかった（faster-whisper のパッケージが無い）")
        raise StartupError("VAD のモデルを開けませんでした: faster-whisper のパッケージが見つかりません")
    model_path = Path(next(iter(spec.submodule_search_locations))) / VAD_MODEL_RELATIVE_PATH
    if not model_path.is_file():
        logger.error(f"VAD を読めなかった（モデルのファイルが無い: {model_path}）")
        raise StartupError(f"VAD のモデルを開けませんでした: {model_path} がありません")

    # 2. 推論のスレッドを 1 つにして CPU で開く（faster-whisper の SileroVADModel と同じ設定）
    options = ort.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.log_severity_level = ORT_LOG_SEVERITY_FATAL
    try:
        return ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
    except Exception as error:  # noqa: BLE001 onnxruntime が送出する例外の型は決まっていない
        logger.exception(f"VAD を読めなかった（{error}）")
        raise StartupError(f"VAD のモデルを開けませんでした: {error}") from error


class StreamingVad:
    """窓ごとに話し声の確率を返し、LSTM の状態と前の窓の末尾を次の窓へ持ち越す。"""

    def __init__(self, session: ort.InferenceSession) -> None:
        """Silero VAD のセッションを受け、状態と文脈を 0 にする。"""
        self._session = session
        self._h = np.zeros(VAD_STATE_SHAPE, dtype=np.float32)
        self._c = np.zeros(VAD_STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros(VAD_CONTEXT, dtype=np.float32)

    def __call__(self, window: np.ndarray) -> float:
        """1 窓（512 サンプル・float32・-1.0〜1.0）の話し声の確率を返し、状態を次の窓へ持ち越す。"""
        # 1. 前の窓の末尾と窓をつないだ (1, 576) の入力を作る
        features = np.concatenate([self._context, window]).reshape(1, -1).astype(np.float32)

        # 2. 確率と新しい h・c を受ける
        probability, self._h, self._c = self._session.run(
            None, {"input": features, "h": self._h, "c": self._c}
        )

        # 3. 窓の末尾を次の文脈として持ち越す
        self._context = window[-VAD_CONTEXT:].copy()
        return float(probability[0])
