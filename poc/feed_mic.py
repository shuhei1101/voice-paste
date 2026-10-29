"""WAV の PCM を、module-pipe-source の FIFO へ実時間の速さで書き込む（PoC）。"""

import argparse
import os
import time
import wave

CHUNK_SEC = 0.1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--fifo", default="/tmp/vp-mic.fifo")
    parser.add_argument("--lead-silence-sec", type=float, default=0.0)
    parser.add_argument("--tail-silence-sec", type=float, default=0.0)
    args = parser.parse_args()

    with wave.open(args.wav, "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        pcm = w.readframes(w.getnframes())
    bytes_per_sec = rate * width * channels
    chunk = int(bytes_per_sec * CHUNK_SEC)
    silence = bytes(chunk)

    fd = os.open(args.fifo, os.O_WRONLY)
    start = time.monotonic()
    sent = 0

    def write(data: bytes) -> None:
        nonlocal sent
        os.write(fd, data)
        sent += 1
        # 書き込んだ量が実時間に追いつくまで待つ
        delay = start + sent * CHUNK_SEC - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    for _ in range(int(args.lead_silence_sec / CHUNK_SEC)):
        write(silence)
    for i in range(0, len(pcm), chunk):
        part = pcm[i : i + chunk]
        write(part + bytes(chunk - len(part)))
    for _ in range(int(args.tail_silence_sec / CHUNK_SEC)):
        write(silence)
    os.close(fd)


if __name__ == "__main__":
    main()
