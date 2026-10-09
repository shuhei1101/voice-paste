"""処理中の開始へのエラーの応答時間（busy_response_time）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し（録音の入力は無音の WAV を実時間で流すもの、システム音量は
何もしないものに差し替えて、実機のマイクを開かない）、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせる。
API のセッションを処理中にしたまま開始を続けて呼び、409 が決定値以内に返り、2 つ目の録音が始まらないことを測る。
ホットキーの受付はまだ新しい構成に無いため、処理中は API で始めたセッションにする。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.fixtures import receiver, start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import InProcessApi, InProcessApp, make_settings, silence_input

pytestmark = pytest.mark.real_machine

TRIALS = 20
"""処理中の開始を呼ぶ回数。"""

RESPONSE_LIMIT_MS = 1000
"""処理中の開始へのエラーの応答時間の決定値（ミリ秒）。"""

RECORD_SEC = 0.5
SILENCE_SEC = 2.0
"""流す無音の WAV の長さ（RECORD_SEC より長くする）。"""

RECEIVE_TIMEOUT_SEC = 30.0
SESSION_LOGGER = "voice_paste.features.session.service"
"""セッションの管理のロガーの名前。"""

SESSION_START_LOG = "セッションを始めた"
"""セッションを始めたときのログの言葉。"""

NO_SPEECH_VAD_THRESHOLD = 1.0
"""どんな音も音声とみなさない無音の区間を除く閾値。"""


def _call_busy(api: InProcessApi, receiver: CallbackReceiver, trials: int) -> list[tuple[int, float]]:
    """処理中の開始を trials 回呼び、毎回のステータスと応答時間（ミリ秒）を並べて返す。"""
    results: list[tuple[int, float]] = []
    for _ in range(trials):
        response, elapsed_ms = api.start_session(receiver.url)
        results.append((response.status_code, elapsed_ms))
    return results


def _count_session_starts(caplog: pytest.LogCaptureFixture) -> int:
    """控えたログから、セッションを始めた回数を数える。"""
    return sum(SESSION_START_LOG in record.getMessage() for record in caplog.records)


def test_busy_response_time(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    receiver: CallbackReceiver,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """処理中に開始を呼ぶと 409 が決定値以内に返り、2 つ目の録音が始まらない（実機）。"""
    # 準備
    caplog.set_level(logging.INFO, logger=SESSION_LOGGER)
    app = start_inprocess(
        settings=make_settings(vad_threshold=NO_SPEECH_VAD_THRESHOLD),
        wav_input=silence_input(tmp_path, seconds=SILENCE_SEC, realtime=True),
    )
    api = app.start_api()
    response, _elapsed_ms = api.start_session(receiver.url)
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    # 実行
    results = _call_busy(api, receiver, TRIALS)

    # 検証
    elapsed_list = [elapsed_ms for _status, elapsed_ms in results]
    print(  # noqa: T201 測った値を実行の出力に残す
        f"busy_response_time: n={len(elapsed_list)} min={min(elapsed_list):.1f} "
        f"max={max(elapsed_list):.1f} ms"
    )
    assert [status for status, _elapsed_ms in results] == [409] * TRIALS
    assert max(elapsed_list) <= RESPONSE_LIMIT_MS
    # 処理中のセッションが続いていて、録音を始めたのは 1 回だけである
    time.sleep(RECORD_SEC)
    assert api.post(f"/sessions/{session_id}/stop").status_code == 200
    assert api.post(f"/sessions/{session_id}/complete").status_code == 202
    assert wait_until(lambda: len(receiver.received) >= 1, RECEIVE_TIMEOUT_SEC)
    assert _count_session_starts(caplog) == 1
    assert [payload["session_id"] for payload in receiver.received] == [session_id]
