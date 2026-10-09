"""刷新の前後での起こした文字の一致を確かめる特性テスト（非機能要件テスト）。

新しい構成の文字起こし（WhisperWorkerClient・transcribe）と補正（load_glossary・apply_glossary）で
起こして補正し、刷新前（voice_paste_legacy）が固めた期待値と比べる。
録音・用語集・設定・期待値は git 管理外の tests/nfr/fixtures/ から読む。
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.support.whisper_fixtures import (
    FIXTURES_DIR,
    RECORDINGS_DIR,
    WORKER_READY_TIMEOUT_SEC,
    WORKER_STOP_TIMEOUT_SEC,
    YOGO_FILE,
    load_local_whisper_settings,
)

if TYPE_CHECKING:
    from voice_paste.integrations.whisper.client import WhisperWorkerClient

EXPECTED_DIR = FIXTURES_DIR / "expected"
CORRECTION_CASES_FILE = FIXTURES_DIR / "correction_cases.json"

RECORDINGS = sorted(RECORDINGS_DIR.glob("*.wav"))
CORRECTION_CASES: list[dict[str, str]] = (
    json.loads(CORRECTION_CASES_FILE.read_text(encoding="utf-8"))
    if CORRECTION_CASES_FILE.exists()
    else []
)


@pytest.fixture(scope="module")
def worker_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WhisperWorkerClient]:
    """固めた設定で文字起こしワーカーの窓口を立てる。ワーカーは終了時に止める。"""
    from voice_paste.integrations.whisper.client import WhisperWorkerClient

    client = WhisperWorkerClient(
        settings=load_local_whisper_settings(),
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=tmp_path_factory.mktemp("log"),
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
    )
    client.start()
    yield client
    client.stop()


@pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("nvidia-smi") is None,
    reason="Windows の NVIDIA GPU が要る",
)
@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda path: path.stem)
def test_transcription_parity_when_history_recordings(
    worker_client: WhisperWorkerClient, recording: Path
) -> None:
    """履歴から選んだ録音を起こして補正した文字が、固めた期待値と一致する（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary, load_glossary
    from voice_paste.features.transcription.service import transcribe

    # 準備
    glossary = load_glossary(YOGO_FILE)
    expected = (EXPECTED_DIR / f"{recording.stem}.txt").read_bytes().decode("utf-8")
    # 実行
    transcribed = transcribe(recording, engine=worker_client.transcribe)
    actual = apply_glossary(transcribed, glossary)
    # 検証
    assert actual == expected


@pytest.mark.skipif(not YOGO_FILE.exists(), reason="tests/nfr/fixtures/ の用語集が要る")
@pytest.mark.parametrize("case", CORRECTION_CASES, ids=lambda case: case["id"])
def test_transcription_parity_when_correction_only(case: dict[str, str]) -> None:
    """用語集の補正だけを切り出し、決まった入力に決まった出力を返す（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary, load_glossary

    # 準備
    glossary = load_glossary(YOGO_FILE)
    # 実行
    actual = apply_glossary(case["input"], glossary)
    # 検証
    assert actual == case["expected"]
