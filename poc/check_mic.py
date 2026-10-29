"""sounddevice の既定の入力から 5 秒録り、RMS を流した WAV と比べる（PoC）。"""

import argparse
import json
import subprocess
import sys
import wave

import numpy as np
import sounddevice as sd

RATE = 16000
SECONDS = 5.0


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


def record() -> np.ndarray:
    data = sd.rec(int(RATE * SECONDS), samplerate=RATE, channels=1, dtype="int16")
    sd.wait()
    return data[:, 0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    args = parser.parse_args()

    with wave.open(args.wav, "rb") as w:
        source = np.frombuffer(w.readframes(int(RATE * SECONDS)), dtype=np.int16)

    print("default input:", sd.query_devices(kind="input")["name"], file=sys.stderr)
    silent = record()
    feeder = subprocess.Popen([sys.executable, "poc/feed_mic.py", args.wav])
    fed = record()
    feeder.wait()

    result = {
        "rms_wav": rms(source),
        "rms_silent": rms(silent),
        "rms_fed": rms(fed),
    }
    result["fed_over_wav"] = result["rms_fed"] / result["rms_wav"]
    result["fed_over_silent"] = (
        result["rms_fed"] / result["rms_silent"] if result["rms_silent"] else None
    )
    result["pass"] = result["fed_over_wav"] >= 0.5 and (
        result["rms_silent"] == 0 or result["fed_over_silent"] >= 10
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
