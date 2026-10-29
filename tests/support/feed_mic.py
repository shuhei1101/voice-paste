"""WAV の PCM を、PipeWire の module-pipe-source の FIFO へ実時間の速さで書き込む。"""

from __future__ import annotations

import argparse
import os
import time
import wave

CHUNK_SEC: float = 0.1
"""FIFO へ書き込む 1 回分の長さ（秒）。"""

DEFAULT_FIFO: str = "/tmp/vp-mic.fifo"  # noqa: S108 仮想マイクを作る置き場所と揃える
"""仮想マイクの FIFO の既定の置き場所。"""


def feed_wav(
    wav_path: str, fifo_path: str, lead_silence_sec: float, tail_silence_sec: float
) -> None:
    """WAV の PCM を前後の無音つきで FIFO へ実時間の速さで書き込む。"""
    with wave.open(wav_path, "rb") as wav:
        bytes_per_sec = wav.getframerate() * wav.getsampwidth() * wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    chunk_bytes = int(bytes_per_sec * CHUNK_SEC)
    silence = bytes(chunk_bytes)

    # 前の無音・PCM（最後の端数は無音で埋める）・後ろの無音を、1 回分ずつの並びにする
    chunks = [silence] * int(lead_silence_sec / CHUNK_SEC)
    for start in range(0, len(pcm), chunk_bytes):
        part = pcm[start : start + chunk_bytes]
        chunks.append(part + bytes(chunk_bytes - len(part)))
    chunks.extend([silence] * int(tail_silence_sec / CHUNK_SEC))

    fd = os.open(fifo_path, os.O_WRONLY)
    try:
        begin = time.monotonic()
        for sent, chunk in enumerate(chunks, start=1):
            os.write(fd, chunk)
            # 書き込んだ量が実時間に追いつくまで待つ（速く書くと録音の長さと合わない）
            delay = begin + sent * CHUNK_SEC - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    finally:
        os.close(fd)


def main() -> None:
    """引数を読んで WAV を FIFO へ流す。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", help="流す WAV（仮想マイクのサンプルレート・チャンネル数に揃える）")
    parser.add_argument("--fifo", default=DEFAULT_FIFO)
    parser.add_argument("--lead-silence-sec", type=float, default=0.0)
    parser.add_argument("--tail-silence-sec", type=float, default=0.0)
    args = parser.parse_args()
    feed_wav(args.wav, args.fifo, args.lead_silence_sec, args.tail_silence_sec)


if __name__ == "__main__":
    main()
