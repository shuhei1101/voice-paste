"""integrations/openai/client.py（transcribe_with_openai）の単体テスト。"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from pydantic import SecretStr

from voice_paste.shared.settings import OpenAISettings

CLIENT_CLASS_PATH = "voice_paste.integrations.openai.client.OpenAI"
MAX_UPLOAD_BYTES = 20_000_000
REQUEST_TIMEOUT_SEC = 30.0
MAX_RETRIES = 1


@pytest.fixture
def openai_class(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """OpenAI のクライアントのクラスを差し替える（生成されるクライアントは return_value）。"""
    class_mock = MagicMock()
    monkeypatch.setattr(CLIENT_CLASS_PATH, class_mock)
    return class_mock


@pytest.fixture
def create_transcription(openai_class: MagicMock) -> MagicMock:
    """差し替えたクライアントの audio.transcriptions.create を返す。"""
    return openai_class.return_value.audio.transcriptions.create


@pytest.fixture
def settings() -> OpenAISettings:
    """API キーつきの OpenAI の設定（既定と違う言語・温度）を返す。"""
    return OpenAISettings(
        api_key=SecretStr("sk-test"), model="whisper-1", language="en", temperature=0.2
    )


@pytest.fixture
def audio_path(tmp_path: Path) -> Path:
    """送れる大きさの録音のファイルを返す。"""
    path = tmp_path / "recording.wav"
    path.write_bytes(b"\0" * 100)
    return path


# === transcribe_with_openai ===


def test_transcribe_with_openai_when_too_large(
    tmp_path: Path,
    settings: OpenAISettings,
    create_transcription: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上限を超える録音は送らない（異常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai
    from voice_paste.shared.errors import EngineError

    # 準備
    too_large = tmp_path / "too_large.wav"
    too_large.write_bytes(b"\0" * 1001)
    caplog.set_level(logging.WARNING)

    # 実行・検証
    with pytest.raises(EngineError):
        transcribe_with_openai(
            too_large,
            settings=settings,
            max_upload_bytes=1000,
            request_timeout_sec=REQUEST_TIMEOUT_SEC,
            max_retries=MAX_RETRIES,
        )
    create_transcription.assert_not_called()
    assert len([record for record in caplog.records if record.levelname == "WARNING"]) == 1


def test_transcribe_with_openai(
    audio_path: Path, settings: OpenAISettings, create_transcription: MagicMock
) -> None:
    """区間ごとの文字を返し、進みを知らせる（正常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai

    # 準備
    create_transcription.return_value = SimpleNamespace(
        segments=[SimpleNamespace(text="今日は", end=1.0), SimpleNamespace(text="晴れ", end=2.0)],
        duration=2.0,
        text="今日は晴れ",
    )
    progress_calls: list[tuple[float, float]] = []

    # 実行
    segments = transcribe_with_openai(
        audio_path,
        on_progress=lambda end, duration: progress_calls.append((end, duration)),
        settings=settings,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        request_timeout_sec=REQUEST_TIMEOUT_SEC,
        max_retries=MAX_RETRIES,
    )

    # 検証
    assert segments == ["今日は", "晴れ"]
    assert progress_calls == [(1.0, 2.0), (2.0, 2.0)]
    request = create_transcription.call_args.kwargs
    assert request["model"] == "whisper-1"
    assert request["language"] == "en"
    assert request["temperature"] == 0.2
    assert request["response_format"] == "verbose_json"


def test_transcribe_with_openai_when_not_whisper_1(
    audio_path: Path, settings: OpenAISettings, create_transcription: MagicMock
) -> None:
    """区間を返さないモデルは json で送り、全文を 1 つ返す（正常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai

    # 準備
    not_whisper_1 = settings.model_copy(update={"model": "gpt-4o-transcribe"})
    create_transcription.return_value = SimpleNamespace(text="今日は晴れ")

    # 実行
    segments = transcribe_with_openai(
        audio_path,
        settings=not_whisper_1,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        request_timeout_sec=REQUEST_TIMEOUT_SEC,
        max_retries=MAX_RETRIES,
    )

    # 検証
    assert segments == ["今日は晴れ"]
    request = create_transcription.call_args.kwargs
    assert request["model"] == "gpt-4o-transcribe"
    assert request["response_format"] == "json"


def test_transcribe_with_openai_when_api_error(
    audio_path: Path, settings: OpenAISettings, create_transcription: MagicMock
) -> None:
    """API のエラーを EngineError にする（異常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai
    from voice_paste.shared.errors import EngineError

    # 準備
    failure = openai.APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    )
    create_transcription.side_effect = failure

    # 実行・検証
    with pytest.raises(EngineError) as exc_info:
        transcribe_with_openai(
            audio_path,
            settings=settings,
            max_upload_bytes=MAX_UPLOAD_BYTES,
            request_timeout_sec=REQUEST_TIMEOUT_SEC,
            max_retries=MAX_RETRIES,
        )
    assert exc_info.value.__cause__ is failure


def test_transcribe_with_openai_when_api_key_empty(
    audio_path: Path, openai_class: MagicMock, create_transcription: MagicMock
) -> None:
    """API キーが空なら送らない（異常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai
    from voice_paste.shared.errors import EngineError

    # 準備
    no_api_key = OpenAISettings(api_key=SecretStr(""))

    # 実行・検証
    with pytest.raises(EngineError):
        transcribe_with_openai(
            audio_path,
            settings=no_api_key,
            max_upload_bytes=MAX_UPLOAD_BYTES,
            request_timeout_sec=REQUEST_TIMEOUT_SEC,
            max_retries=MAX_RETRIES,
        )
    create_transcription.assert_not_called()


def test_transcribe_with_openai_when_timeout_and_retries_given(
    audio_path: Path,
    settings: OpenAISettings,
    openai_class: MagicMock,
    create_transcription: MagicMock,
) -> None:
    """タイムアウトと再試行の回数をクライアントへ明示して渡す（正常系）。"""
    from voice_paste.integrations.openai.client import transcribe_with_openai

    # 準備
    create_transcription.return_value = SimpleNamespace(text="今日は晴れ")

    # 実行
    transcribe_with_openai(
        audio_path,
        settings=settings,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        request_timeout_sec=30.0,
        max_retries=1,
    )

    # 検証
    client_arguments = openai_class.call_args.kwargs
    assert client_arguments["timeout"] == 30.0
    assert client_arguments["max_retries"] == 1
