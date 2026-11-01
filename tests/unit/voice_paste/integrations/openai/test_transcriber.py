"""integrations/openai/transcriber.py（OpenAITranscriber.transcribe・_build_form）の単体テスト。

送信先は httpx.MockTransport に、待つ関数・待つ秒数のジッターを引く関数は記録する関数に差し替える。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from voice_paste.shared.errors import EngineError

BASE_URL = "http://127.0.0.1:9000/v1"
TRANSCRIPTIONS_URL = "http://127.0.0.1:9000/v1/audio/transcriptions"
API_KEY = "sk-test-key"
MODEL = "gpt-4o-mini-transcribe"
KEYWORDS_MODEL = "gpt-transcribe"
LANGUAGE = "ja"
HINT = "voice-paste、Whisper"
WAV_BYTES = b"RIFF0000WAVEfmt "


class FakeEndpoint:
    """届いた要求を覚え、台本の応答（httpx.Response か送出する例外）を 1 要求に 1 つずつ返すエンドポイント。"""

    def __init__(self, *script: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self._script = list(script)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """要求を覚え、台本の次の応答を返す（例外なら送出する）。"""
        self.requests.append(request)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _form_parts(request: httpx.Request) -> list[tuple[str, bytes]]:
    """multipart の本文を、届いた順の（欄の名前, 値）に分ける（同じ名前の欄は繰り返し並ぶ。file は音声のバイト列）。"""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts: list[tuple[str, bytes]] = []
    for part in request.content.split(b"--" + boundary):
        head, separator, body = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if not separator or name is None:
            continue
        parts.append((name.group(1).decode(), body.removesuffix(b"\r\n")))
    return parts


def _form_fields(request: httpx.Request) -> dict[str, bytes]:
    """multipart の本文を、欄の名前 → 値（file は音声のバイト列）に分ける。"""
    return dict(_form_parts(request))


def _ok(text: str) -> httpx.Response:
    """文字起こしに成功した応答（200 と text）。"""
    return httpx.Response(200, json={"text": text})


@pytest.fixture
def audio_path(tmp_path: Path) -> Path:
    """送信する録音の WAV。"""
    path = tmp_path / "recording.wav"
    path.write_bytes(WAV_BYTES)
    return path


@pytest.fixture
def sleep() -> MagicMock:
    """送信し直す前に待つ関数の偽物（待たずに呼び出しだけを覚える）。"""
    return MagicMock(return_value=None)


@pytest.fixture
def uniform() -> MagicMock:
    """待つ秒数のジッターを引く関数の偽物（範囲の上限をそのまま返す）。"""
    return MagicMock(side_effect=lambda low, high: high)


@pytest.fixture
def make_transcriber(sleep: MagicMock, uniform: MagicMock) -> Callable[..., Any]:
    """エンドポイントへ送信する OpenAITranscriber を作る関数（モデルは省くと MODEL）を返す。"""

    def _make(endpoint: FakeEndpoint, model: str = MODEL) -> Any:
        """MockTransport でエンドポイントへつないだ OpenAITranscriber を作る。"""
        from voice_paste.integrations.openai.transcriber import OpenAITranscriber
        from voice_paste.shared.settings import OpenAISettings

        return OpenAITranscriber(
            settings=OpenAISettings(model=model, language=LANGUAGE, base_url=BASE_URL),
            api_key=SecretStr(API_KEY),
            sleep=sleep,
            uniform=uniform,
            transport=httpx.MockTransport(endpoint),
        )

    return _make


def test_transcribe(audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]) -> None:
    """録音と設定を送信して起こした文字を返す（正常系）。"""
    # 準備
    endpoint = FakeEndpoint(_ok(" 今日は晴れ "))
    transcriber = make_transcriber(endpoint)

    # 実行
    segments = transcriber.transcribe(audio_path, hint=HINT)

    # 検証
    assert segments == ["今日は晴れ"]
    assert len(endpoint.requests) == 1
    request = endpoint.requests[0]
    assert str(request.url) == TRANSCRIPTIONS_URL
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    fields = _form_fields(request)
    assert fields["file"] == WAV_BYTES
    assert fields["model"] == MODEL.encode()
    assert fields["language"] == LANGUAGE.encode()
    assert fields["response_format"] == b"json"
    assert fields["prompt"] == HINT.encode()


def test_transcribe_when_no_hint(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """手がかりが無ければ prompt を送信しない（正常系）。"""
    # 準備
    endpoint = FakeEndpoint(_ok("今日は晴れ"))
    transcriber = make_transcriber(endpoint)

    # 実行
    transcriber.transcribe(audio_path, hint=None)

    # 検証
    assert "prompt" not in _form_fields(endpoint.requests[0])


def test_transcribe_when_empty_text(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """起こした文字が空なら空の並びを返す（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(_ok("")))

    # 実行
    segments = transcriber.transcribe(audio_path)

    # 検証
    assert segments == []


def test_transcribe_when_retry_after(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any], sleep: MagicMock
) -> None:
    """429 は Retry-After を待って送信し直す（正常系）。"""
    # 準備: 1 回目が 429 と Retry-After: 2、2 回目が 200
    endpoint = FakeEndpoint(httpx.Response(429, headers={"Retry-After": "2"}), _ok("今日は晴れ"))
    transcriber = make_transcriber(endpoint)

    # 実行
    segments = transcriber.transcribe(audio_path)

    # 検証
    sleep.assert_called_once_with(2.0)
    assert segments == ["今日は晴れ"]


def test_transcribe_when_server_error_retried(
    audio_path: Path,
    make_transcriber: Callable[[FakeEndpoint], Any],
    sleep: MagicMock,
    uniform: MagicMock,
) -> None:
    """5xx とタイムアウトは待って送信し直す（正常系）。"""
    # 準備: 1 回目が 503、2 回目が ReadTimeout、3 回目が 200
    endpoint = FakeEndpoint(httpx.Response(503), httpx.ReadTimeout("timeout"), _ok("今日は晴れ"))
    transcriber = make_transcriber(endpoint)

    # 実行
    segments = transcriber.transcribe(audio_path)

    # 検証: 待つ秒数のジッターを (0, 0.5)・(0, 1.0) で引き、その秒数だけ待って起こした文字を返す
    assert [call.args for call in uniform.call_args_list] == [(0, 0.5), (0, 1.0)]
    assert [call.args for call in sleep.call_args_list] == [(0.5,), (1.0,)]
    assert len(endpoint.requests) == 3
    assert segments == ["今日は晴れ"]


def test_transcribe_when_retry_exhausted(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """回数の上限まで失敗したら EngineError にする（異常系）。"""
    # 準備: 3 回とも 500
    endpoint = FakeEndpoint(httpx.Response(500), httpx.Response(500), httpx.Response(500))
    transcriber = make_transcriber(endpoint)

    # 実行・検証
    with pytest.raises(EngineError, match="500"):
        transcriber.transcribe(audio_path)
    assert len(endpoint.requests) == 3


def test_transcribe_when_unauthorized(
    audio_path: Path,
    make_transcriber: Callable[[FakeEndpoint], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """401 は送信し直さずに EngineError にし、API キーを書かない（異常系）。"""
    # 準備
    caplog.set_level(logging.DEBUG)
    endpoint = FakeEndpoint(
        httpx.Response(
            401, json={"error": {"type": "invalid_request_error", "code": "invalid_api_key"}}
        )
    )
    transcriber = make_transcriber(endpoint)

    # 実行
    with pytest.raises(EngineError, match="401") as exc_info:
        transcriber.transcribe(audio_path)

    # 検証: 要求は 1 回で、例外の理由に error.code が入り、例外にもログにも API キーが入らない
    assert len(endpoint.requests) == 1
    assert "invalid_api_key" in str(exc_info.value)
    assert API_KEY not in str(exc_info.value)
    assert API_KEY not in caplog.text


def test_transcribe_when_audio_too_large(
    tmp_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """25 MB を超える音声は送信しない（異常系）。"""
    from voice_paste.integrations.openai.transcriber import OPENAI_MAX_AUDIO_BYTES

    # 準備: 上限より 1 バイト大きい webm
    audio_path = tmp_path / "recording.webm"
    with audio_path.open("wb") as file:
        file.truncate(OPENAI_MAX_AUDIO_BYTES + 1)
    endpoint = FakeEndpoint()
    transcriber = make_transcriber(endpoint)

    # 実行・検証
    with pytest.raises(EngineError, match="上限（25 MB）"):
        transcriber.transcribe(audio_path)
    assert endpoint.requests == []


def test_transcribe_when_unsupported_suffix(
    tmp_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """受けられない形式は送信しない（異常系）。"""
    # 準備: 拡張子が .ogg の音声
    audio_path = tmp_path / "recording.ogg"
    audio_path.write_bytes(b"OggS")
    endpoint = FakeEndpoint()
    transcriber = make_transcriber(endpoint)

    # 実行・検証
    with pytest.raises(EngineError, match="ogg"):
        transcriber.transcribe(audio_path)
    assert endpoint.requests == []


def test_transcribe_when_redirected(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """リダイレクトを追わない（異常系）。"""
    # 準備: 307 で別のホストを指す（追ってしまえば 2 回目の要求が別のホストへ出て 200 が返る）
    endpoint = FakeEndpoint(
        httpx.Response(307, headers={"Location": "https://other.example/v1/audio/transcriptions"}),
        _ok("今日は晴れ"),
    )
    transcriber = make_transcriber(endpoint)

    # 実行・検証
    with pytest.raises(EngineError, match="307"):
        transcriber.transcribe(audio_path)
    assert [request.url.host for request in endpoint.requests] == ["127.0.0.1"]


def test_transcribe_when_keywords_model(
    audio_path: Path, make_transcriber: Callable[..., Any]
) -> None:
    """gpt-transcribe では keywords[] と languages[] を同じ項目名で繰り返して送信する（正常系）。"""
    # 準備
    endpoint = FakeEndpoint(_ok("今日は晴れ"))
    transcriber = make_transcriber(endpoint, KEYWORDS_MODEL)

    # 実行
    segments = transcriber.transcribe(audio_path, hint=HINT)

    # 検証: keywords[] が 2 つ・languages[] が 1 つ並び、language・prompt は届かない
    assert segments == ["今日は晴れ"]
    parts = _form_parts(endpoint.requests[0])
    assert [value for name, value in parts if name == "keywords[]"] == [b"voice-paste", b"Whisper"]
    assert [value for name, value in parts if name == "languages[]"] == [b"ja"]
    assert "language" not in dict(parts)
    assert "prompt" not in dict(parts)
    assert dict(parts)["model"] == KEYWORDS_MODEL.encode()


def test_transcribe_when_no_timeout(
    audio_path: Path, make_transcriber: Callable[[FakeEndpoint], Any]
) -> None:
    """待つ時間の上限を設けずに送信する（正常系）。"""
    # 準備
    endpoint = FakeEndpoint(_ok("今日は晴れ"))
    transcriber = make_transcriber(endpoint)

    # 実行
    transcriber.transcribe(audio_path)

    # 検証: httpx の既定の 5 秒が掛かっていない
    assert endpoint.requests[0].extensions["timeout"] == {
        "connect": None,
        "read": None,
        "write": None,
        "pool": None,
    }


def test_build_form_when_keywords_model(make_transcriber: Callable[..., Any]) -> None:
    """gpt-transcribe は語を keywords[]、言語を languages[] に入れる（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(), KEYWORDS_MODEL)

    # 実行
    form = transcriber._build_form(HINT)

    # 検証: language・prompt は入らない
    assert form == {"languages[]": ["ja"], "keywords[]": ["voice-paste", "Whisper"]}


def test_build_form_when_keywords_model_snapshot(make_transcriber: Callable[..., Any]) -> None:
    """gpt-transcribe で始まるスナップショットも keywords[] で渡す（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(), "gpt-transcribe-2026-08-26")

    # 実行
    form = transcriber._build_form("voice-paste")

    # 検証
    assert form["keywords[]"] == ["voice-paste"]
    assert form["languages[]"] == ["ja"]


def test_build_form_when_keywords_model_no_hint(make_transcriber: Callable[..., Any]) -> None:
    """手がかりが無ければ keywords[] を入れない（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(), KEYWORDS_MODEL)

    # 実行
    form = transcriber._build_form(None)

    # 検証
    assert form == {"languages[]": ["ja"]}


def test_build_form_when_forbidden_keyword(
    make_transcriber: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    """< か > を含む語は keywords[] に入れない（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    transcriber = make_transcriber(FakeEndpoint(), KEYWORDS_MODEL)

    # 実行
    form = transcriber._build_form("<tag>、Whisper、a>b")

    # 検証: 残る語は Whisper だけで、WARNING には除いた語の数 2 が書かれ、語そのものは書かれない
    assert form["keywords[]"] == ["Whisper"]
    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1
    assert "2" in warnings[0]
    assert "<tag>" not in caplog.text
    assert "a>b" not in caplog.text


def test_build_form_when_all_keywords_forbidden(make_transcriber: Callable[..., Any]) -> None:
    """全ての語が除かれたら keywords[] を入れない（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(), KEYWORDS_MODEL)

    # 実行
    form = transcriber._build_form("<tag>")

    # 検証
    assert form == {"languages[]": ["ja"]}


def test_build_form_when_previous_model(make_transcriber: Callable[..., Any]) -> None:
    """前のモデルは今のまま language と prompt に入れる（正常系）。"""
    # 準備
    transcriber = make_transcriber(FakeEndpoint(), "gpt-4o-mini-transcribe")

    # 実行
    form = transcriber._build_form(HINT)

    # 検証: languages[]・keywords[] は入らない
    assert form == {"language": "ja", "prompt": HINT}
