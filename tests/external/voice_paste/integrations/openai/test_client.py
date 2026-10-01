"""integrations/openai/client.py（transcribe_with_openai）の外部疎通テスト。

OpenAI API へ実際に接続し、1 秒の録音 1 回分の従量課金がかかる。
`--run-external` を付けたときだけ走り、環境変数 `OPENAI_API_KEY` が無ければ skip する。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import SecretStr
from scipy.io import wavfile

from voice_paste.shared.settings import OpenAISettings

API_KEY_ENV: str = "OPENAI_API_KEY"
SAMPLE_RATE = 16000
MAX_UPLOAD_BYTES = 20_000_000  # 非機能要件の OpenAI API へ送る音声ファイルの大きさの決定値
# 非機能要件のタイムアウトと再試行は未確定のため、疎通を確かめるための仮の値を置く
PROVISIONAL_REQUEST_TIMEOUT_SEC = 60.0
PROVISIONAL_MAX_RETRIES = 1


@pytest.fixture
def api_key() -> str:
    """環境変数の OpenAI の API キーを返す。無ければ skip する。"""
    value = os.environ.get(API_KEY_ENV, "")
    if not value:
        pytest.skip(f"環境変数 {API_KEY_ENV} が無い")
    return value


def test_ext_transcribe_with_openai_when_default_model(tmp_path: Path, api_key: str) -> None:
    """既定のモデルで短い録音を起こせる（正常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai

    # 準備（1 秒の無音の録音。区間の有無ではなく、認証と応答の形を確かめる）
    audio_path = tmp_path / "one_second.wav"
    wavfile.write(audio_path, SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.int16))
    settings = OpenAISettings(api_key=SecretStr(api_key))
    progress_calls: list[tuple[float, float]] = []

    # 実行
    segments = transcribe_with_openai(
        audio_path,
        on_progress=lambda end, duration: progress_calls.append((end, duration)),
        settings=settings,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        request_timeout_sec=PROVISIONAL_REQUEST_TIMEOUT_SEC,
        max_retries=PROVISIONAL_MAX_RETRIES,
    )

    # 検証（認証が通って、区間ごとの文字（str のリスト）が返り、進みは区間の終わりと長さの組）
    assert isinstance(segments, list)
    assert all(isinstance(segment, str) for segment in segments)
    assert all(0 <= end <= duration for end, duration in progress_calls)
