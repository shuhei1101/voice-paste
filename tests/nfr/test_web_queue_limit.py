"""ブラウザの音声の待ちの上限（web_queue_limit）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて、
文字起こしのエンジンを、テストが放すまで戻らない関数に差し替え、小さい webm を `POST /web/transcriptions` で 11 回送信する。
履歴を残さない設定にして、終わっていないジョブの音声が全て一時のフォルダにある状態で数える
（履歴を残す設定では、動き出したジョブの音声は履歴へ移るため、一時のフォルダには待ちの分だけが残る）。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import make_audio, wait_until
from tests.support.fixtures import start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import InProcessApi, InProcessApp, make_settings, silence_input, stub_transcription
from tests.support.settings import load_test_default_settings
from tests.support.web_scene import STUB_TEXT

pytestmark = pytest.mark.real_machine

QUEUE_LIMIT = 10
"""終わっていないジョブの上限（件）。"""


def _send_statuses(api: InProcessApi, audio: bytes, count: int) -> list[int]:
    """audio を count 回送信し、毎回のステータスを返す。"""
    return [api.post_web_audio(audio).status_code for _ in range(count)]


def test_web_queue_limit(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """終わっていないジョブが 10 件あるとき次の受け付けは 503 になり、エンジンを放して 1 件終わると次の受け付けが 202 になる（実機）。"""
    # 準備
    stub = stub_transcription(monkeypatch, STUB_TEXT)
    stub.hold()
    settings = make_settings(only_paste_and_send=True).model_copy(
        update={
            "history": load_test_default_settings().history.model_copy(update={"enabled": False})
        }
    )
    app = start_inprocess(settings=settings, wav_input=silence_input(tmp_path))
    api = app.start_web_api()
    audio = make_audio("webm", tmp_path)

    # 実行
    statuses = _send_statuses(api, audio, QUEUE_LIMIT + 1)
    files_when_full = app.web_temp_files()
    stub.release.set()
    freed = wait_until(lambda: len(app.web_temp_files()) < QUEUE_LIMIT)
    next_status = api.post_web_audio(audio).status_code

    # 検証
    assert statuses == [202] * QUEUE_LIMIT + [503]
    assert len(files_when_full) == QUEUE_LIMIT
    assert freed
    assert next_status == 202
