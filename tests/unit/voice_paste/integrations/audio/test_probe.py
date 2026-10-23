"""integrations/audio/probe.py（probe_audio）の単体テスト。

本物の PyAV で、ブラウザが録った形式（Edge が録った webm/opus・fragmented MP4）と、
テストの中で書き出した WAV・ogg・MP3 の形式・秒数を読む。
"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest
from scipy.io import wavfile

FIXTURES = Path(__file__).parent / "fixtures"
"""PR #171 の PoC で Edge の MediaRecorder が録った音声の置き場所。"""

SAMPLE_RATE = 16000
"""書き出す WAV のサンプリングレート。"""

TONE_SEC = 1.0
"""書き出す音声の長さ（秒）。"""

DURATION_TOLERANCE_SEC = 0.2
"""読んだ秒数と元の音声の秒数の許容差。"""

EDGE_WEBM_SEC = 10.956
"""Edge が録った webm/opus の秒数（PoC で WAV の長さから求めた値）。"""

EDGE_MP4_SEC = 10.941
"""Edge が録った fragmented MP4（AAC）の秒数（PoC で WAV の長さから求めた値）。"""


def _write_wav(path: Path) -> Path:
    """1 秒の音をモノラルの 16 bit の WAV で書く。"""
    t = np.arange(int(SAMPLE_RATE * TONE_SEC)) / SAMPLE_RATE
    samples = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    wavfile.write(path, SAMPLE_RATE, samples)
    return path


def _encode(source: Path, target: Path, container: str, codec: str, rate: int) -> Path:
    """WAV を指定のコンテナとコーデックへ書き直す。"""
    with av.open(str(source)) as src, av.open(str(target), "w", format=container) as dst:
        stream = dst.add_stream(codec, rate=rate)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=stream.rate)
        for frame in src.decode(audio=0):
            for resampled in resampler.resample(frame):
                dst.mux(stream.encode(resampled))
        for resampled in resampler.resample(None):
            dst.mux(stream.encode(resampled))
        dst.mux(stream.encode(None))
    return target


def _make_audio(kind: str, tmp_path: Path) -> Path:
    """kind の形式の音声のファイルを用意して、そのパスを返す。"""
    wav = _write_wav(tmp_path / "tone.wav")
    if kind == "wav":
        return wav
    if kind == "ogg":
        return _encode(wav, tmp_path / "tone.ogg", "ogg", "libopus", 48000)
    if kind == "mp3":
        return _encode(wav, tmp_path / "tone.mp3", "mp3", "libmp3lame", 44100)
    if kind == "webm":
        return FIXTURES / "edge_audio.webm"
    return FIXTURES / "edge_audio.mp4"


def _write_video_only_mp4(path: Path) -> Path:
    """音声のストリームを持たない、映像だけの mp4 を書く。"""
    with av.open(str(path), "w", format="mp4") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for _ in range(10):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
            out.mux(stream.encode(frame))
        out.mux(stream.encode(None))
    return path


def _make_unreadable(kind: str, tmp_path: Path) -> Path:
    """kind の読めない中身のファイルを用意して、そのパスを返す。"""
    if kind == "text":
        text_path = tmp_path / "notes.mp3"
        text_path.write_text("これは音声ではありません", encoding="utf-8")
        return text_path
    return _write_video_only_mp4(tmp_path / "video.mp4")


@pytest.mark.parametrize(
    ("kind", "suffix", "expected_sec"),
    [
        pytest.param("webm", ".webm", EDGE_WEBM_SEC, id="edge_webm_opus_without_cues"),
        pytest.param("mp4", ".mp4", EDGE_MP4_SEC, id="edge_fragmented_mp4_aac"),
        pytest.param("wav", ".wav", TONE_SEC, id="wav"),
        pytest.param("ogg", ".ogg", TONE_SEC, id="ogg"),
        pytest.param("mp3", ".mp3", TONE_SEC, id="mp3"),
    ],
)
def test_probe_audio(kind: str, suffix: str, expected_sec: float, tmp_path: Path) -> None:
    """録れた形式を読む（正常系）。"""
    from voice_paste.integrations.audio.probe import probe_audio

    # 準備
    audio_path = _make_audio(kind, tmp_path)

    # 実行
    with audio_path.open("rb") as file:
        probe = probe_audio(file)
        position = file.tell()

    # 検証
    assert probe.suffix == suffix
    assert probe.duration_sec == pytest.approx(expected_sec, abs=DURATION_TOLERANCE_SEC)
    assert probe.size_bytes == audio_path.stat().st_size
    assert position == 0


@pytest.mark.parametrize("kind", [
    pytest.param("text", id="text_content"),
    pytest.param("video_only", id="mp4_without_audio_stream"),
])
def test_probe_audio_when_unreadable(kind: str, tmp_path: Path) -> None:
    """音声でない中身と音声の無い mp4 は断る（異常系）。"""
    from voice_paste.integrations.audio.probe import probe_audio
    from voice_paste.shared.errors import AudioUnreadableError

    # 準備
    unreadable_path = _make_unreadable(kind, tmp_path)

    # 実行・検証
    with unreadable_path.open("rb") as file, pytest.raises(AudioUnreadableError):
        probe_audio(file)
