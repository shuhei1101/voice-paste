"""OpenAI の文字起こしのタイムアウトと再送（openai_transcription_retry）の非機能要件テスト。

OpenAITranscriber の送信先は httpx.MockTransport に、待つ関数と待つ秒数のジッターを引く関数は記録する関数に差し替える。
実際の OpenAI API へは送信せず、実機も要らない。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from tests.support.settings import load_test_default_settings
from pydantic import SecretStr

from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import OpenAISettings

BASE_URL = "http://127.0.0.1:9000/v1"
"""テストが送信先に向ける、OpenAI API のベース URL の代わり。"""

REQUESTS_IN_TOTAL = 3
"""最初の 1 回と、再送の回数の上限（2 回）を合わせた要求の回数。"""


def test_openai_transcription_retry(tmp_path: Path) -> None:
    """一時的な失敗を上限まで送信し直し、それでも失敗したら EngineError にする（一時的な失敗は 500 が 3 回続く）。"""
    from voice_paste.integrations.openai.transcriber import OpenAITranscriber

    # 準備: 500 を返し続ける送信先と、待たない・上限をそのまま返す偽物
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """要求を控えて 500 を返す。"""
        requests.append(request)
        return httpx.Response(500)

    sleep = MagicMock(return_value=None)
    uniform = MagicMock(side_effect=lambda _low, high: high)
    transcriber = OpenAITranscriber(
        settings=load_test_default_settings().transcription.openai.model_copy(update={"base_url": BASE_URL}),
        api_key=SecretStr("sk-test"),
        sleep=sleep,
        uniform=uniform,
        transport=httpx.MockTransport(handler),
    )
    audio_path = tmp_path / "recording.wav"
    audio_path.write_bytes(b"RIFF0000WAVEfmt ")

    # 実行
    with pytest.raises(EngineError):
        transcriber.transcribe(audio_path)

    # 検証: 要求は 3 回で、待つ秒数のジッターの上限は 0.5・1.0
    assert len(requests) == REQUESTS_IN_TOTAL
    assert [call.args for call in uniform.call_args_list] == [(0, 0.5), (0, 1.0)]
