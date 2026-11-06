"""受けた音声のバイト列を、モデルへ渡す 16 kHz モノラルの配列にする。"""

from __future__ import annotations

import io

import av
import av.error
import numpy as np

SAMPLE_RATE: int = 16000
"""モデルのサンプリングレート。"""


class AudioDecodeError(Exception):
    """受けた音声を復号できない。"""


def decode_audio(data: bytes) -> np.ndarray:
    """受けた音声（WAV・webm・ogg・mp4 など）を PyAV で復号し、16 kHz モノラルの float32 の 1 次元配列にする。"""
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    try:
        with av.open(io.BytesIO(data)) as container:
            # 音声のストリームが無ければ起こせない
            if not container.streams.audio:
                raise AudioDecodeError("音声のストリームが無い")
            for frame in container.decode(audio=0):
                chunks.extend(_to_samples(part) for part in resampler.resample(frame))
            chunks.extend(_to_samples(part) for part in resampler.resample(None))
    except av.error.FFmpegError as error:
        raise AudioDecodeError(f"音声を読めない（{error}）") from error
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def _to_samples(frame: av.AudioFrame) -> np.ndarray:
    """モノラルのフレームを 1 次元の配列にする。"""
    return frame.to_ndarray()[0]
