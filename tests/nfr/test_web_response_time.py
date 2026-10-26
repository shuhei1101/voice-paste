"""ブラウザの要求の応答時間（web_response_time）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて、
本文が 99,000,000 バイトになる webm の音声を `POST /web/transcriptions` で 5 回送信し、送信し始めてから 202 を受けるまでを測る。
文字起こしのエンジンは、受けたパスを控えて決めた文を返す関数に差し替える。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import make_audio
from tests.support.fixtures import start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import InProcessApi, InProcessApp, make_settings, silence_input, stub_transcription
from tests.support.web_scene import STUB_TEXT
from tests.support.web_body import sized_multipart_body

pytestmark = pytest.mark.real_machine

BODY_BYTES = 99_000_000
"""送信する本文の大きさ（バイト。上限に近い）。"""

SEND_COUNT = 5
"""送信する回数。"""

RESPONSE_LIMIT_SEC = 66
"""受け付けの応答時間の決定値（秒）。"""


def _send_times(api: InProcessApi, body: bytes, count: int) -> tuple[list[int], list[float]]:
    """body を count 回送信し、毎回のステータスと、送信し始めてから応答を受けるまでの時間（秒）を返す。"""
    statuses: list[int] = []
    elapsed_list: list[float] = []
    for _ in range(count):
        started = time.perf_counter()
        response = api.post_web_body(body)
        elapsed_list.append(time.perf_counter() - started)
        statuses.append(response.status_code)
    return statuses, elapsed_list


def test_web_response_time(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本文が 99,000,000 バイトの音声の受け付けが、5 回とも 202 で、最大が決定値（66 秒）以内に返る（実機）。"""
    # 準備
    stub_transcription(monkeypatch, STUB_TEXT)
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api()
    body = sized_multipart_body(make_audio("webm", tmp_path), BODY_BYTES)

    # 実行
    statuses, elapsed_list = _send_times(api, body, SEND_COUNT)

    # 検証
    print(  # noqa: T201 測った値を実行の出力に残す
        f"web_response_time: n={len(elapsed_list)} min={min(elapsed_list):.2f} "
        f"max={max(elapsed_list):.2f} sec"
    )
    assert statuses == [202] * SEND_COUNT
    assert max(elapsed_list) <= RESPONSE_LIMIT_SEC
