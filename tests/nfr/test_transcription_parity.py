"""刷新前の文字起こしと用語集の補正を固める特性テスト（非機能要件テスト）。

録音・用語集・設定・期待値は git 管理外の tests/nfr/fixtures/ から読む。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values

from voice_paste_legacy import config
from voice_paste_legacy.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste_legacy.utils import apply_yogo_replacements, load_yogo

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RECORDINGS_DIR = FIXTURES_DIR / "recordings"
EXPECTED_DIR = FIXTURES_DIR / "expected"
YOGO_FILE = FIXTURES_DIR / "yogo.csv"
WHISPER_ENV_FILE = FIXTURES_DIR / "whisper.env"
CORRECTION_CASES_FILE = FIXTURES_DIR / "correction_cases.json"

# CUDA の DLL を持つ nvidia-* パッケージ（venv の site-packages/nvidia/{名前}/bin）
CUDA_DLL_PACKAGES = ("cublas", "cudnn", "cuda_nvrtc")


def _to_bool(value: str) -> bool:
    """config.py と同じ規則で true / false の文字を bool にする。"""
    return value.lower() == "true"


# 固めた設定のうち文字起こしが読む config の変数と、config.py と同じ型への変換
SETTING_PARSERS: dict[str, Callable[[str], object]] = {
    "WHISPER_MODEL": str,
    "WHISPER_DEVICE": str,
    "WHISPER_COMPUTE_TYPE": str,
    "WHISPER_CPU_THREADS": int,
    "WHISPER_NUM_WORKERS": int,
    "WHISPER_BEAM_SIZE": int,
    "WHISPER_BEST_OF": int,
    "WHISPER_LANGUAGE": str,
    "WHISPER_VAD_FILTER": _to_bool,
    "WHISPER_VAD_THRESHOLD": float,
    "WHISPER_VAD_MIN_SPEECH_MS": int,
    "WHISPER_VAD_MIN_SILENCE_MS": int,
    "WHISPER_CONDITION_ON_PREVIOUS_TEXT": _to_bool,
    "WHISPER_TEMPERATURE": float,
    "WHISPER_NO_SPEECH_THRESHOLD": float,
}

RECORDINGS = sorted(RECORDINGS_DIR.glob("*.wav"))
CORRECTION_CASES: list[dict[str, str]] = (
    json.loads(CORRECTION_CASES_FILE.read_text(encoding="utf-8"))
    if CORRECTION_CASES_FILE.exists()
    else []
)


@pytest.fixture(scope="module")
def whisper_transcriber() -> Iterator[WhisperTranscriber]:
    """固めた設定と CUDA の DLL の経路で WhisperTranscriber を立てる。ワーカーは終了時に止まる。"""
    settings = dotenv_values(WHISPER_ENV_FILE)
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    cuda_dirs = [str(site_packages / "nvidia" / name / "bin") for name in CUDA_DLL_PACKAGES]
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key, parse in SETTING_PARSERS.items():
            monkeypatch.setattr(config, key, parse(settings[key] or ""))
        # ワーカーのサブプロセスが CUDA の DLL を見つけられるよう PATH の先頭に足す
        monkeypatch.setenv("PATH", os.pathsep.join([*cuda_dirs, os.environ["PATH"]]))
        yield WhisperTranscriber()


@pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("nvidia-smi") is None,
    reason="Windows の NVIDIA GPU が要る",
)
@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda path: path.stem)
def test_transcription_parity_when_history_recordings(
    whisper_transcriber: WhisperTranscriber, recording: Path
) -> None:
    """履歴から選んだ録音を起こして補正した文字が、固めた期待値と一致する（正常系）。"""
    # 準備
    glossary = load_yogo(YOGO_FILE)
    expected = (EXPECTED_DIR / f"{recording.stem}.txt").read_bytes().decode("utf-8")
    # 実行
    transcribed = whisper_transcriber.transcribe(recording)
    actual = apply_yogo_replacements(transcribed, glossary)
    # 検証
    assert actual == expected


@pytest.mark.parametrize("case", CORRECTION_CASES, ids=lambda case: case["id"])
def test_transcription_parity_when_correction_only(case: dict[str, str]) -> None:
    """用語集の補正だけを切り出し、決まった入力に決まった出力を返す（正常系）。"""
    # 準備
    glossary = load_yogo(YOGO_FILE)
    # 実行
    actual = apply_yogo_replacements(case["input"], glossary)
    # 検証
    assert actual == case["expected"]
