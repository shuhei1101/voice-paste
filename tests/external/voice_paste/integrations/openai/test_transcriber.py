"""integrations/openai/transcriber.py（OpenAITranscriber.transcribe）の外部疎通テスト。

実際の OpenAI API（POST /v1/audio/transcriptions）へ短い日本語の音声を送信する。従量課金がかかる（既定のモデル gpt-transcribe で 1 回あたり約 $0.0003）。
API キー（環境変数 `OPENAI_API_KEY` か、設定の置き場所の `secrets/openai_api_key`）が無い環境と、音声を作れない環境（Windows の音声合成が無い）では skip する。
かかった秒を記録する（非機能要件のタイムアウトを実測で見直す材料）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from voice_paste.shared.errors import StartupError

SPOKEN_TEXT = "今日はいい天気ですね。散歩に行きましょう。"
"""読み上げて送信する、約 3 秒の日本語の文。"""

HINT = "voice-paste、Whisper"
"""keywords[] に付ける手がかり。"""


@pytest.fixture
def api_key() -> SecretStr:
    """API キー（環境変数か秘匿のファイル）を返す。無ければ skip する。"""
    from voice_paste.integrations.openai.credentials import read_openai_api_key
    from voice_paste.shared.constants import resolve_app_paths

    try:
        return read_openai_api_key(resolve_app_paths(None).openai_api_key_file, os.environ)
    except StartupError as error:
        pytest.skip(f"OpenAI の API キーが無い環境のため実行しない（{error}）")


@pytest.fixture
def spoken_wav(tmp_path: Path) -> Path:
    """SPOKEN_TEXT を読み上げた WAV を返す。Windows の音声合成が無い環境では skip する。"""
    if sys.platform != "win32":
        pytest.skip("Windows の音声合成（SAPI）が無い環境のため実行しない")
    from tests.support.inprocess import synthesize_speech

    return synthesize_speech(SPOKEN_TEXT, tmp_path / "spoken.wav")


def test_ext_transcribe(
    api_key: SecretStr, spoken_wav: Path, record_property: pytest.RecordProperty
) -> None:
    """実際の OpenAI API で、既定のモデル（gpt-transcribe）・languages[]=ja・keywords[] 付きの短い音声を起こせる（正常系）。"""
    from voice_paste.integrations.openai.transcriber import OpenAITranscriber
    from voice_paste.shared.settings import OpenAISettings

    # 準備
    settings = OpenAISettings()
    transcriber = OpenAITranscriber(settings=settings, api_key=api_key)

    # 実行
    started = time.perf_counter()
    segments = transcriber.transcribe(spoken_wav, hint=HINT)
    elapsed_sec = time.perf_counter() - started
    record_property("elapsed_sec", f"{elapsed_sec:.2f}")
    print(f"OpenAI API の文字起こしにかかった秒: {elapsed_sec:.2f}")

    # 検証: 既定のモデルは gpt-transcribe で、空でない文字が 1 区間で返る
    assert settings.model == "gpt-transcribe"
    assert len(segments) == 1
    assert segments[0] != ""
