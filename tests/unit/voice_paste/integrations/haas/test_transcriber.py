"""integrations/haas/transcriber.py（HaasTranscriber.transcribe）の単体テスト。

送信先は httpx.MockTransport に差し替える。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from voice_paste.shared.errors import EngineError

if TYPE_CHECKING:
    from voice_paste.shared.settings import HintVocabularyWord

PORT = 47824
TRANSCRIPTIONS_URL = f"http://127.0.0.1:{PORT}/transcriptions"
WAV_BYTES = b"RIFF0000WAVEfmt "


def _form_fields(request: httpx.Request) -> dict[str, bytes]:
    """multipart の本文を（欄の名前 → 値）に分ける。"""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    fields: dict[str, bytes] = {}
    for part in request.content.split(b"--" + boundary):
        head, separator, body = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if separator and name is not None:
            fields[name.group(1).decode()] = body.removesuffix(b"\r\n")
    return fields


def _transcribe(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    vocabulary: list[HintVocabularyWord] | None = None,
) -> list[str]:
    """録音のファイルを作り、差し替えた送信先で transcribe を呼ぶ。"""
    from voice_paste.integrations.haas.transcriber import HaasTranscriber

    audio_path = tmp_path / "recording.wav"
    audio_path.write_bytes(WAV_BYTES)
    transcriber = HaasTranscriber(
        port=PORT,
        get_vocabulary=lambda: vocabulary or [],
        transport=httpx.MockTransport(handler),
    )
    return transcriber.transcribe(audio_path)


def test_transcribe(tmp_path: Path) -> None:
    """録音と語を送信して起こした文字を返す（正常系）。"""
    from voice_paste.shared.settings import HintVocabularyWord

    # 準備
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """要求を覚えて、起こした文字を返す。"""
        requests.append(request)
        return httpx.Response(200, json={"text": " 今日は晴れ "})

    # 実行
    result = _transcribe(
        tmp_path,
        handler,
        [HintVocabularyWord("突合", "とつごう"), HintVocabularyWord("voice-paste", None)],
    )

    # 検証
    assert result == ["今日は晴れ"]
    assert str(requests[0].url) == TRANSCRIPTIONS_URL
    fields = _form_fields(requests[0])
    assert fields["audio"] == WAV_BYTES
    assert json.loads(fields["vocabulary"]) == [
        {"written": "突合", "reading": "とつごう"},
        {"written": "voice-paste", "reading": None},
    ]


def test_transcribe_when_no_vocabulary(tmp_path: Path) -> None:
    """語が無ければ vocabulary を送信しない（正常系）。"""
    # 準備
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """要求を覚えて、起こした文字を返す。"""
        requests.append(request)
        return httpx.Response(200, json={"text": "文字"})

    # 実行
    _transcribe(tmp_path, handler)

    # 検証
    assert "vocabulary" not in _form_fields(requests[0])


def test_transcribe_when_empty_text(tmp_path: Path) -> None:
    """起こした文字が空なら空の並びを返す（正常系）。"""
    # 実行
    result = _transcribe(tmp_path, lambda _request: httpx.Response(200, json={"text": ""}))

    # 検証
    assert result == []


def test_transcribe_when_server_error(tmp_path: Path) -> None:
    """サーバーが失敗を返したら EngineError を送出する（異常系）。"""
    # 準備
    response = httpx.Response(500, json={"detail": "GPU のメモリが足りない"})

    # 実行・検証
    with pytest.raises(EngineError) as exc_info:
        _transcribe(tmp_path, lambda _request: response)
    assert "500" in str(exc_info.value)
    assert "GPU のメモリが足りない" in str(exc_info.value)


def _raise_connect_error(_request: httpx.Request) -> httpx.Response:
    """接続できない。"""
    raise httpx.ConnectError("refused")


def _raise_read_timeout(_request: httpx.Request) -> httpx.Response:
    """応答がタイムアウトする。"""
    raise httpx.ReadTimeout("timeout")


def test_transcribe_when_unreachable(tmp_path: Path) -> None:
    """接続できなければ EngineError を送出する（異常系）。"""
    # 実行・検証
    with pytest.raises(EngineError):
        _transcribe(tmp_path, _raise_connect_error)


def test_transcribe_when_timeout(tmp_path: Path) -> None:
    """応答がタイムアウトすれば EngineError を送出する（異常系）。"""
    # 実行・検証
    with pytest.raises(EngineError):
        _transcribe(tmp_path, _raise_read_timeout)
