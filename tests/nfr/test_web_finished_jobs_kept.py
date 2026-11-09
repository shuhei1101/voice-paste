"""終わったジョブを持つ件数（web_finished_jobs_kept）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて、
文字起こしのエンジンを決めた文をすぐ返す関数に差し替え、小さい webm を `POST /web/transcriptions` で 101 回送信して全て done にする。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import make_audio, wait_until
from tests.support.fixtures import start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import (
    STUB_TEXT,
    InProcessApi,
    InProcessApp,
    make_settings,
    silence_input,
    stub_transcription,
    requires_web_transcription,
)

pytestmark = [pytest.mark.real_machine, requires_web_transcription]

FINISHED_KEPT = 100
"""終わったジョブを持つ件数。"""


def _send_and_finish(api: InProcessApi, audio: bytes, count: int) -> list[str]:
    """audio を count 回送信し、1 件ずつ done になるのを待って、ジョブの ID を送信した順に返す。"""
    job_ids: list[str] = []
    for _ in range(count):
        response = api.post_web_audio(audio)
        assert response.status_code == 202
        job_id = str(response.json()["job_id"])
        assert wait_until(lambda: api.get_job(job_id).json().get("state") == "done")
        job_ids.append(job_id)
    return job_ids


def test_web_finished_jobs_kept(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """終わったジョブが 100 件を超えると、1 件目が 404 になり、2 件目と 101 件目は done で取れる（実機）。"""
    # 準備
    stub_transcription(monkeypatch, STUB_TEXT)
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api()
    audio = make_audio("webm", tmp_path)

    # 実行
    job_ids = _send_and_finish(api, audio, FINISHED_KEPT + 1)
    first = api.get_job(job_ids[0])
    second = api.get_job(job_ids[1])
    last = api.get_job(job_ids[-1])

    # 検証
    assert len(job_ids) == FINISHED_KEPT + 1
    assert first.status_code == 404
    assert second.status_code == 200
    assert second.json()["state"] == "done"
    assert last.status_code == 200
    assert last.json()["state"] == "done"
