"""Windows の faster-whisper（今の文字起こしワーカーと同じ設定）で検証の音声を起こし、結果を JSON に書く。

voice-paste の Windows の Python で動かす: `python bench_whisper.py {音声のフォルダ} {結果の JSON}`
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path

# 文字起こしワーカーと同じく、venv の nvidia-* の DLL の場所を PATH の先頭へ追加する
_NVIDIA_ROOT = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
os.environ["PATH"] = os.pathsep.join(
    [str(_NVIDIA_ROOT / name / "bin") for name in ("cublas", "cudnn", "cuda_nvrtc")] + [os.environ["PATH"]]
)

from faster_whisper import WhisperModel  # noqa: E402 DLL の場所を追加した後に読み込む

from sentences import HINT_WORDS

# config/defaults.yaml の transcription.local_whisper と同じ値
MODEL = "large-v3"
OPTIONS = {
    "language": "ja",
    "beam_size": 10,
    "best_of": 5,
    "temperature": 0.0,
    "vad_filter": True,
    "vad_parameters": {"threshold": 0.5, "min_speech_duration_ms": 250, "min_silence_duration_ms": 2000},
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
}
# join_hint_words と同じく読点でつなぐ
HOTWORDS = "、".join(written for written, _ in HINT_WORDS)
REPEATS = 3


def _transcribe(model: WhisperModel, wav: Path, hotwords: str | None) -> tuple[float, str]:
    """1 件を起こし、区間を読み終えるまでの秒数と、区間を改行でつないだ文字を返す。"""
    begin = time.perf_counter()
    segments, _ = model.transcribe(str(wav), hotwords=hotwords, **OPTIONS)
    text = "\n".join(segment.text.strip() for segment in segments)
    return time.perf_counter() - begin, text


def main(audio_dir: Path, out_path: Path) -> None:
    """モデルを読み込み、音声ごと・手がかりの有無ごとに測って書く。"""
    manifest = json.loads((audio_dir / "manifest.json").read_text(encoding="utf-8"))
    begin = time.perf_counter()
    model = WhisperModel(MODEL, device="cuda", compute_type="float16")
    results: dict[str, object] = {"model_load_sec": round(time.perf_counter() - begin, 2), "runs": []}
    # 最初の 1 件（初回の CUDA の準備を含む）の時間を別に控える
    first_sec, _ = _transcribe(model, audio_dir / manifest[0]["file"], HOTWORDS)
    results["first_request_sec"] = round(first_sec, 3)
    for item in manifest:
        for label, hotwords in (("none", None), ("hotwords", HOTWORDS)):
            runs = [_transcribe(model, audio_dir / item["file"], hotwords) for _ in range(REPEATS)]
            results["runs"].append(
                {
                    "id": item["id"],
                    "vocab": label,
                    "sec": round(statistics.median(t for t, _ in runs), 3),
                    "text": runs[-1][1],
                }
            )
            print(item["id"], label, results["runs"][-1]["sec"], runs[-1][1][:40].replace("\n", " "))
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
