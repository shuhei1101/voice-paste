"""PoC #179: 文字起こしのオプションの組み合わせごとに履歴の録音を起こし、起こした文字と処理時間を results.json に書く。

録音は git 管理外の tests/nfr/fixtures/poc_hallucination/ に控えた履歴の wav と txt から読む。
設定は %APPDATA%/voice-paste/settings.toml の transcription.local_whisper を基準にする。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from voice_paste.integrations.whisper.client import WhisperWorkerClient  # noqa: E402
from voice_paste.shared.settings import HintPresetSettings, LocalWhisperSettings, join_hint_words  # noqa: E402

RECORDINGS_DIR = REPO_ROOT / "tests" / "nfr" / "fixtures" / "poc_hallucination"
RESULTS_FILE = Path(__file__).resolve().parent / "results.json"
SETTINGS_FILE = Path(os.environ["APPDATA"]) / "voice-paste" / "settings.toml"

READY_TIMEOUT_SEC = 120.0
"""モデルの読み込みを待つ上限（float16 の large-v3 を初めて読む時間を含む）。"""

STOP_TIMEOUT_SEC = 2.0
"""ワーカーの終わりを待つ時間（非機能要件の決定値）。"""

CLEAN_COUNT = 20
"""定型句が出ていない群に取る録音の数。"""

HALLUCINATION_IDS = (
    "20261023005513",
    "20261023105437",
    "20261023232155",
    "20261024032112",
    "20261023115828",
    "20261023130220",
    "20261023231941",
    "20261024162257",
)
"""定型句の候補の群の録音（ファイル名の先頭の日時）。後ろの 4 件はユーザーが話していないと答えたもの。"""

COMBINATIONS: dict[str, dict[str, object]] = {
    "base": {},
    "B1": {"word_timestamps": True},
    "B2": {"word_timestamps": True, "hallucination_silence_threshold": 1.0},
    "B3": {"word_timestamps": True, "hallucination_silence_threshold": 2.0},
}
"""比べる組み合わせ（基準の設定に重ねるオプション）。"""


def _select_recordings() -> dict[str, list[Path]]:
    """定型句の候補の群と、文字が空でない残りから先頭 CLEAN_COUNT 件の群を返す。"""
    wavs = sorted(RECORDINGS_DIR.glob("*.wav"))
    hallucination = [wav for wav in wavs if wav.name[:14] in HALLUCINATION_IDS]
    clean: list[Path] = []
    for wav in wavs:
        txt = wav.with_suffix(".txt")
        # 候補の群と、起こした文字の無い録音は除く
        if wav in hallucination or not txt.exists() or not txt.read_text(encoding="utf-8").strip():
            continue
        clean.append(wav)
        if len(clean) == CLEAN_COUNT:
            break
    return {"hallucination": hallucination, "clean": clean}


def _run_combination(
    base: LocalWhisperSettings,
    overrides: dict[str, object],
    recordings: list[Path],
    hint: str | None,
    log_dir: Path,
) -> dict[str, dict[str, object]]:
    """1 つの組み合わせでワーカーを立て、録音を 1 件ずつ起こして行と時間を返す。"""
    client = WhisperWorkerClient(
        settings=base.model_copy(update=overrides),
        ready_timeout_sec=READY_TIMEOUT_SEC,
        log_dir=log_dir,
        stop_timeout_sec=STOP_TIMEOUT_SEC,
    )
    client.start(ready_timeout_sec=READY_TIMEOUT_SEC)
    results: dict[str, dict[str, object]] = {}
    try:
        for wav in recordings:
            started = time.perf_counter()
            lines = client.transcribe(wav, hint=hint)
            results[wav.name] = {"lines": lines, "elapsed_sec": time.perf_counter() - started}
    finally:
        client.stop()
    return results


def main() -> None:
    """全ての組み合わせで録音を起こし、results.json に書く。"""
    logging.basicConfig(level=logging.INFO)
    # 使う 2 つの表だけを検証する（ほかの表には、このブランチより新しいキーが入っていることがある）
    document = tomllib.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    base = LocalWhisperSettings.model_validate(document["transcription"]["local_whisper"])
    presets = [HintPresetSettings.model_validate(preset) for preset in document.get("hint_presets", [])]
    # 本番と同じく、有効なヒントの語から手がかりを作る（無ければ None）
    hint = join_hint_words(presets) or None
    groups = _select_recordings()
    recordings = groups["hallucination"] + groups["clean"]
    output: dict[str, object] = {
        "settings": base.model_dump(),
        "hint": hint,
        "groups": {name: [wav.name for wav in wavs] for name, wavs in groups.items()},
        "combinations": {},
    }
    with tempfile.TemporaryDirectory() as log_dir:
        for name, overrides in COMBINATIONS.items():
            logging.info(f"組み合わせ {name} で起こす（{overrides}）")
            output["combinations"][name] = {  # type: ignore[index]
                "overrides": overrides,
                "recordings": _run_combination(base, overrides, recordings, hint, Path(log_dir)),
            }
    RESULTS_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
