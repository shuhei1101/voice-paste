"""PoC #179: compare.py の results.json を成功条件（定型句の消え方・話した文字の欠け）に照らし、表を report.md に書く。"""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_FILE = HERE / "results.json"
REPORT_FILE = HERE / "report.md"

PHRASE = re.compile(r"(ご視聴)?ありがとうございました[。.!！]?$")
"""話していない定型句の行（「ご視聴ありがとうございました」か、単独の「ありがとうございました」）。"""

HALLUCINATION_REMOVED_RATIO = 3 / 4
"""成功条件 (1): 基準で定型句が出た録音のうち、消えていなければならない割合。"""

MIN_HALLUCINATION_BASE = 2
"""成功条件 (1) を判定できる、基準で定型句が出た録音の最少件数。"""

MAX_CHANGE_RATIO = 0.05
"""成功条件 (2): 定型句の出ない群で許す、基準の文字数に対する編集距離の割合。"""

MISSING_LINE_RATIO = 0.5
"""基準の行に最も近い候補の行の編集距離の割合がこれを超えたら、その行は欠けたとみなす。"""


def _distance(left: str, right: str) -> int:
    """2 つの文字列の編集距離（レーベンシュタイン距離）を返す。"""
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left_char != right_char))
            )
        previous = current
    return previous[-1]


def _has_phrase(lines: list[str]) -> bool:
    """起こした行に定型句の行が含まれるか。"""
    return any(PHRASE.fullmatch(line.strip()) for line in lines)


def _missing_lines(base: list[str], candidate: list[str]) -> list[str]:
    """基準の行のうち、候補のどの行とも近くない（欠けた）行を返す。"""
    missing: list[str] = []
    for line in base:
        # 候補に行が無ければ全て欠けている
        if not candidate:
            missing.append(line)
            continue
        nearest = min(_distance(line, other) / max(len(line), 1) for other in candidate)
        if nearest > MISSING_LINE_RATIO:
            missing.append(line)
    return missing


def main() -> None:
    """組み合わせごとに成功条件 (1)(2) を判定して report.md に書く。"""
    data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    combinations = data["combinations"]
    base_runs = combinations["base"]["recordings"]
    hallucination = data["groups"]["hallucination"]
    clean = data["groups"]["clean"]

    # 成功条件 (1) の分母: 基準で定型句が出た録音
    base_hits = [name for name in hallucination if _has_phrase(base_runs[name]["lines"])]
    required = math.ceil(len(base_hits) * HALLUCINATION_REMOVED_RATIO)

    lines = [
        "# PoC #179 の結果",
        "",
        f"基準で定型句が出た録音: {len(base_hits)} / {len(hallucination)} 件（{', '.join(n[:14] for n in base_hits)}）",
        "",
        "| 組み合わせ | 定型句が消えた | (1) | 定型の無い群の最大の変化率 | 欠けた行 | (2) | 定型の無い群で新たに出た定型句 | 処理時間の中央値（秒） |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    details: list[str] = []
    for name, combination in combinations.items():
        runs = combination["recordings"]
        removed = [n for n in base_hits if not _has_phrase(runs[n]["lines"])]
        # 基準が判定できる件数に届かなければ (1) は判定できない
        criterion1 = "判定不可" if len(base_hits) < MIN_HALLUCINATION_BASE else ("○" if len(removed) >= required else "×")
        ratios: list[float] = []
        missing_total = 0
        new_phrases = 0
        for recording in clean:
            base_lines = base_runs[recording]["lines"]
            candidate_lines = runs[recording]["lines"]
            base_text = "".join(base_lines)
            ratio = _distance(base_text, "".join(candidate_lines)) / max(len(base_text), 1)
            ratios.append(ratio)
            missing = _missing_lines(base_lines, candidate_lines)
            missing_total += len(missing)
            new_phrases += int(_has_phrase(candidate_lines) and not _has_phrase(base_lines))
            if ratio > 0 or missing:
                details.append(f"- {name} / {recording[:14]}: 変化率 {ratio:.3f}、欠けた行 {missing}")
        criterion2 = "○" if max(ratios) <= MAX_CHANGE_RATIO and missing_total == 0 else "×"
        median = statistics.median(run["elapsed_sec"] for run in runs.values())
        lines.append(
            f"| {name} | {len(removed)} / {len(base_hits)} | {criterion1} | {max(ratios):.3f} | {missing_total} | {criterion2} | {new_phrases} | {median:.2f} |"
        )

    # 録音ごとの定型句の出方
    lines += ["", "## 定型句の候補の群", "", "| 録音 | " + " | ".join(combinations) + " |", "| --- |" + " --- |" * len(combinations)]
    for recording in hallucination:
        cells = [
            "定型句あり" if _has_phrase(combination["recordings"][recording]["lines"]) else "なし"
            for combination in combinations.values()
        ]
        lines.append(f"| {recording[:14]} | " + " | ".join(cells) + " |")
    lines += ["", "## 定型句の出ない群で基準と違った録音", "", *details]
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
