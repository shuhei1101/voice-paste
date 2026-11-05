"""検証の音声を Open JTalk（pyopenjtalk）で 3 つの長さに合成し、正解の文と一緒に manifest.json へ書く。

WSL の Haas の環境で動かす: `.venv/bin/python synth.py {出力フォルダ}`
"""

import json
import sys
from pathlib import Path

import librosa
import numpy as np
import pyopenjtalk
import soundfile

from sentences import SENTENCES, render

SAMPLE_RATE = 16000
# 文と文の間に入れる無音の秒数（transcribe_longform が区切る静かな箇所になる）
GAP_SEC = 0.8
# 中くらいの長さは 1 本に入れる文の数。30 秒以下に収まる数にする
MEDIUM_GROUP = 6
# 長い音声は全ての文を何周させるか
LONG_ROUNDS = 3


def _synthesize(text: str) -> np.ndarray:
    """1 文を合成して 16 kHz の float32 にする。"""
    wave, sr = pyopenjtalk.tts(text)
    wave = (wave / 32768.0).astype(np.float32)
    return librosa.resample(wave, orig_sr=sr, target_sr=SAMPLE_RATE)


def _join(waves: list[np.ndarray]) -> np.ndarray:
    """文の音声を無音を挟んでつなぐ。"""
    gap = np.zeros(int(GAP_SEC * SAMPLE_RATE), dtype=np.float32)
    parts: list[np.ndarray] = []
    for wave in waves:
        parts.extend([wave, gap])
    return np.concatenate(parts)


def main(out_dir: Path) -> None:
    """3 つの長さの音声を書き出し、manifest.json に一覧を書く。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = len(SENTENCES)
    # 1. 文ごとに 1 度だけ合成しておく
    waves = [_synthesize(render(i, for_synthesis=True)) for i in range(count)]
    references = [render(i, for_synthesis=False) for i in range(count)]
    words = [SENTENCES[i][0] for i in range(count)]

    # 2. 長さごとに、どの文をどの順で入れるかを決める
    clips: list[tuple[str, str, list[int]]] = []
    clips += [("short", f"short_{i:02d}", [i]) for i in range(count)]
    for start in range(0, count, MEDIUM_GROUP):
        clips.append(("medium", f"medium_{start // MEDIUM_GROUP:02d}", list(range(start, min(start + MEDIUM_GROUP, count)))))
    long_order = [i for _ in range(LONG_ROUNDS) for i in range(count)]
    clips.append(("long", "long_00", long_order))
    clips.append(("long", "long_01", list(reversed(long_order))))

    # 3. 書き出して一覧にする
    manifest = []
    for length_class, clip_id, indexes in clips:
        audio = _join([waves[i] for i in indexes])
        path = out_dir / f"{clip_id}.wav"
        soundfile.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
        manifest.append(
            {
                "id": clip_id,
                "length_class": length_class,
                "file": path.name,
                "duration_sec": round(len(audio) / SAMPLE_RATE, 2),
                "reference": "".join(references[i] for i in indexes),
                "hint_words": [words[i] for i in indexes],
            }
        )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in manifest:
        print(item["id"], item["duration_sec"])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
