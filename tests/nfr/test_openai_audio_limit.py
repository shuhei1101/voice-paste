"""OpenAI へ送信する音声の上限（openai_audio_limit）の非機能要件テスト。

OpenAITranscriber の送信先は httpx.MockTransport に差し替え、上限ちょうどと 1 バイト超えの webm を送信して、届いた要求の数と本文の大きさを確かめる。
手がかり（prompt）は上限（222 バイト）いっぱいにして、要求の本文の固定の消費分が最も大きい場合を測る。
実際の OpenAI API へは送信せず、実機も要らない。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import HINT_MAX_BYTES, OpenAISettings

BASE_URL = "http://127.0.0.1:9000/v1"
"""テストが送信先に向ける、OpenAI API のベース URL の代わり。"""

DECIDED_LIMIT_BYTES = 26_209_484
"""決定値（送信できる音声の大きさの上限）。"""

EXTERNAL_LIMIT_BYTES = 26_214_400
"""外部の上限（25 MB）。要求の本文全体がこれ以下になる。"""

FULL_HINT = "あ" * (HINT_MAX_BYTES // 3)
"""上限いっぱい（222 バイト）の手がかり。"""


def _webm_of(path: Path, size_bytes: int) -> Path:
    """中身が 0 のバイトだけの、size_bytes バイトの webm を作る。"""
    with path.open("wb") as file:
        file.truncate(size_bytes)
    return path


def test_openai_audio_limit_when_over(tmp_path: Path) -> None:
    """上限ちょうどの音声は送信し、1 バイト超える音声は送信せずに EngineError にする。"""
    from voice_paste.integrations.openai.transcriber import OpenAITranscriber

    # 準備: 届いた要求を控えて文字を返す送信先
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """要求を控えて 200 を返す。"""
        requests.append(request)
        return httpx.Response(200, json={"text": "ok"})

    transcriber = OpenAITranscriber(
        settings=OpenAISettings(base_url=BASE_URL),
        api_key=SecretStr("sk-test"),
        transport=httpx.MockTransport(handler),
    )
    at_limit = _webm_of(tmp_path / "at_limit.webm", DECIDED_LIMIT_BYTES)
    over_limit = _webm_of(tmp_path / "over_limit.webm", DECIDED_LIMIT_BYTES + 1)

    # 実行: 上限ちょうどの音声
    transcriber.transcribe(at_limit, hint=FULL_HINT)

    # 検証: 1 回届き、届いた要求の本文が外部の上限以下
    assert len(requests) == 1
    assert len(requests[0].content) <= EXTERNAL_LIMIT_BYTES

    # 実行・検証: 1 バイト超える音声は、新しい要求が届かず EngineError
    with pytest.raises(EngineError):
        transcriber.transcribe(over_limit, hint=FULL_HINT)
    assert len(requests) == 1
