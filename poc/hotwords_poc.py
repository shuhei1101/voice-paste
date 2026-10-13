"""hotwords の手がかりの有無で、起こした文字と処理時間がどう変わるかを比べる PoC。

録音の一覧（1 行 = 1 つの WAV のパス）と条件を受け、条件ごとに 3 回起こした生の出力
（用語集で補正する前）と処理時間を JSON Lines で書く。モデルと transcribe の引数は
settings.toml の [transcription.local_whisper] に揃える。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

CONDITIONS: dict[str, str | None] = {
    "none": None,
    "list": "GitHub、イシュー、プルリクエスト、レビュー、返信、バッジ、暫定対応、恒久対応、voice-paste、PoC、Claude Code",
    "sentence": "GitHub のイシューに返信してレビューする。バッジで件数を出す。暫定対応の後に恒久対応をする。voice-paste で PoC を試す。",
}
"""条件の名前と hotwords に渡す手がかり（none は渡さない）。"""

HOTWORDS_MAX_BYTES: int = 222
"""要件で決めた、つないだ手がかりの UTF-8 のバイト数の上限。"""

RUNS_PER_CONDITION: int = 3
"""条件ごとに 1 つの録音を流す回数（中央値を録音ごとの値にする）。"""

CUDA_DLL_PACKAGES: tuple[str, ...] = ("cublas", "cudnn", "cuda_nvrtc")
"""CUDA の DLL を持つ nvidia-* パッケージ。"""


def _add_cuda_dll_dirs() -> None:
    """venv の nvidia-* パッケージの DLL の場所を読み込み先に足す。"""
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for name in CUDA_DLL_PACKAGES:
        dll_dir = nvidia_root / name / "bin"
        if dll_dir.is_dir():
            os.add_dll_directory(str(dll_dir))
            os.environ["PATH"] = f"{dll_dir}{os.pathsep}{os.environ['PATH']}"


def _load_whisper_settings(settings_path: Path) -> dict[str, Any]:
    """settings.toml の [transcription.local_whisper] を読む。"""
    with settings_path.open("rb") as file:
        return tomllib.load(file)["transcription"]["local_whisper"]


def _transcribe_once(model: Any, audio: Path, whisper: dict[str, Any], hotwords: str | None) -> tuple[str, float, float]:  # noqa: ANN401 faster-whisper のモデル
    """1 回起こし、区間を改行でつないだ文字・処理秒数・VAD の後の秒数を返す。"""
    vad_parameters = None
    # VAD がオンのときだけ、本番のワーカーと同じ VAD の引数を渡す
    if whisper["vad_filter"]:
        vad_parameters = {
            "threshold": whisper["vad_threshold"],
            "min_speech_duration_ms": whisper["vad_min_speech_ms"],
            "min_silence_duration_ms": whisper["vad_min_silence_ms"],
        }
    started = time.perf_counter()
    segments, info = model.transcribe(
        str(audio),
        language=whisper["language"],
        beam_size=whisper["beam_size"],
        best_of=whisper["best_of"],
        temperature=whisper["temperature"],
        vad_filter=whisper["vad_filter"],
        vad_parameters=vad_parameters,
        condition_on_previous_text=whisper["condition_on_previous_text"],
        no_speech_threshold=whisper["no_speech_threshold"],
        hotwords=hotwords,
    )
    # segments は遅延評価なので、読み切るまでを処理時間に入れる
    texts = [segment.text.strip() for segment in segments if segment.text.strip()]
    elapsed = time.perf_counter() - started
    return "\n".join(texts), elapsed, info.duration_after_vad


def main() -> int:
    """録音の一覧を条件ごとに起こし、結果を JSON Lines で書く。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--audio-list", type=Path, required=True)
    parser.add_argument("--conditions", nargs="+", choices=list(CONDITIONS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # 1. 手がかりが要件の上限に収まることを先に確かめる
    for name, hotwords in CONDITIONS.items():
        if hotwords is not None and len(hotwords.encode("utf-8")) > HOTWORDS_MAX_BYTES:
            raise ValueError(f"手がかり {name} が {HOTWORDS_MAX_BYTES} バイトを超えている")

    _add_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    whisper = _load_whisper_settings(args.settings)
    model = WhisperModel(
        whisper["model"],
        device=whisper["device"],
        compute_type=whisper["compute_type"],
        cpu_threads=whisper["cpu_threads"],
        num_workers=whisper["num_workers"],
    )
    audios = [Path(line.strip()) for line in args.audio_list.read_text(encoding="utf-8").splitlines() if line.strip()]

    # 2. CUDA の立ち上がりを外すため、最初の録音を 1 回流して捨てる
    _transcribe_once(model, audios[0], whisper, None)

    # 3. 録音 × 条件ごとに 3 回流し、出力と処理時間の中央値を書く
    with args.output.open("a", encoding="utf-8") as output:
        for audio in audios:
            for name in args.conditions:
                hotwords = CONDITIONS[name]
                runs = [_transcribe_once(model, audio, whisper, hotwords) for _ in range(RUNS_PER_CONDITION)]
                record = {
                    "audio": audio.name,
                    "condition": name,
                    "hotwords_bytes": 0 if hotwords is None else len(hotwords.encode("utf-8")),
                    "texts": [text for text, _, _ in runs],
                    "median_sec": statistics.median(elapsed for _, elapsed, _ in runs),
                    "duration_after_vad": runs[0][2],
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(f"{audio.name} {name} {record['median_sec']:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
