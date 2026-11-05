"""bench_haas.py と bench_whisper.py の結果を、長さごとの CER・表記のヒントの単語の正解率・時間にまとめる。

`python score.py {音声のフォルダ} {haas.json} {whisper.json} {出力の Markdown}`
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from sentences import HINT_WORDS

# 句読点・記号・空白・改行は CER から外す（Whisper は句読点を出し、Haas は出さないため）
_IGNORED = re.compile(r"[\s。、．，,.!?！？「」『』・…ー〜~\-]")


def normalize(text: str) -> str:
    """NFKC と小文字にして、句読点・記号・空白を外す。"""
    return _IGNORED.sub("", unicodedata.normalize("NFKC", text).casefold())


def edit_distance(a: str, b: str) -> int:
    """文字の編集距離を返す。"""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def hint_hits(reference: str, hypothesis: str) -> tuple[int, int]:
    """正解の文に出る表記のヒントの単語のうち、起こした文字にも同じ回数まで出た数と、出るべき数を返す。"""
    ref, hyp = normalize(reference), normalize(hypothesis)
    hit = total = 0
    for written, _ in HINT_WORDS:
        word = normalize(written)
        expected = ref.count(word)
        total += expected
        hit += min(expected, hyp.count(word))
    return hit, total


def _aggregate(manifest: list[dict], texts: dict[str, str], times: dict[str, float]) -> dict[str, dict[str, float]]:
    """長さごとに CER・正解率・時間の合計をまとめる。"""
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for item in manifest:
        bucket = sums[item["length_class"]]
        ref = normalize(item["reference"])
        bucket["edits"] += edit_distance(ref, normalize(texts[item["id"]]))
        bucket["chars"] += len(ref)
        hit, total = hint_hits(item["reference"], texts[item["id"]])
        bucket["hit"] += hit
        bucket["total"] += total
        bucket["sec"] += times[item["id"]]
        bucket["audio_sec"] += item["duration_sec"]
        bucket["clips"] += 1
    return sums


def main(audio_dir: Path, haas_path: Path, whisper_path: Path, out_path: Path) -> None:
    """長さごと・構成ごとの表を Markdown に書く。"""
    manifest = json.loads((audio_dir / "manifest.json").read_text(encoding="utf-8"))
    haas = json.loads(haas_path.read_text(encoding="utf-8"))
    whisper = json.loads(whisper_path.read_text(encoding="utf-8"))
    # 1. 構成ごとに、音声の ID → 起こした文字・時間の表を作る
    configs: dict[str, tuple[dict[str, str], dict[str, float]]] = {}
    for run in whisper["runs"]:
        texts, times = configs.setdefault(f"faster-whisper（{run['vocab']}）", ({}, {}))
        texts[run["id"]], times[run["id"]] = run["text"], run["sec"]
    for run in haas["runs"]:
        texts, times = configs.setdefault(f"Haas（{run['vocab']}・{run['longform_mode']}）", ({}, {}))
        texts[run["id"]], times[run["id"]] = run["text"], run["roundtrip_sec"]
    # 長い音声だけの sequential は、短い・中くらいの音声を batch の値で埋める
    for name in list(configs):
        if name.endswith("sequential）"):
            batch_texts, batch_times = configs[name.replace("sequential", "batch")]
            texts, times = configs[name]
            for item in manifest:
                texts.setdefault(item["id"], batch_texts[item["id"]])
                times.setdefault(item["id"], batch_times[item["id"]])
    # 2. 長さごとにまとめて表にする
    lines = ["| 長さ | 構成 | 本数 | CER | 表記のヒントの単語 | 合計の秒数 | 音声 1 秒あたりの秒数 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for length_class in ("short", "medium", "long"):
        for name, (texts, times) in configs.items():
            bucket = _aggregate(manifest, texts, times)[length_class]
            lines.append(
                f"| {length_class} | {name} | {int(bucket['clips'])} | {bucket['edits'] / bucket['chars']:.2%} "
                f"| {int(bucket['hit'])}/{int(bucket['total'])}（{bucket['hit'] / bucket['total']:.0%}） "
                f"| {bucket['sec']:.2f} | {bucket['sec'] / bucket['audio_sec']:.4f} |"
            )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
