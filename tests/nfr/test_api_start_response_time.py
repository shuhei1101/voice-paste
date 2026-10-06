"""API の開始の応答時間（api_start_response_time）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し（録音の入力は無音の WAV を実時間で流すもの、システム音量は
何もしないものに差し替えて、実機のマイクを開かない）、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて、
開始 → 停止 → 完了を 50 回続けて呼び、50 回とも返送先に文字が届き、開始の応答が決定値以内であることを測る。
返送が速く終わるよう、どんな音も音声とみなさない設定（vad_threshold = 1.0）で起こす。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.fixtures import receiver, start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import InProcessApi, InProcessApp, make_settings, silence_input

pytestmark = pytest.mark.real_machine

CYCLES = 50
"""開始 → 停止 → 完了を続けて呼ぶ回数。"""

RESPONSE_LIMIT_MS = 500
"""開始の応答時間の決定値（ミリ秒）。"""

RECORD_SEC = 0.3
"""開始から停止まで無音を流して録る秒数。"""

SILENCE_SEC = 1.0
"""流す無音の WAV の長さ（RECORD_SEC より長くする）。"""

RECEIVE_TIMEOUT_SEC = 30.0
"""完了から返送が届くまで待つ上限。"""

NO_SPEECH_VAD_THRESHOLD = 1.0
"""どんな音も音声とみなさない無音の区間を除く閾値。"""


def _run_cycles(api: InProcessApi, receiver: CallbackReceiver, cycles: int) -> list[float]:
    """開始 → 停止 → 完了を cycles 回続けて呼び、毎回の返送を待って、開始の応答時間（ミリ秒）を並べて返す。"""
    elapsed_list: list[float] = []
    for index in range(cycles):
        response, elapsed_ms = api.start_session(receiver.url)
        assert response.status_code == 202
        session_id = response.json()["session_id"]
        elapsed_list.append(elapsed_ms)
        time.sleep(RECORD_SEC)
        assert api.post(f"/sessions/{session_id}/stop").status_code == 200
        assert api.post(f"/sessions/{session_id}/complete").status_code == 202
        assert wait_until(lambda: len(receiver.received) >= index + 1, RECEIVE_TIMEOUT_SEC)
    return elapsed_list


def test_api_start_response_time(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    receiver: CallbackReceiver,  # noqa: F811
) -> None:
    """開始 → 停止 → 完了を 50 回続け、50 回とも返送先に文字が届き、開始の応答が決定値以内である（実機）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(vad_threshold=NO_SPEECH_VAD_THRESHOLD),
        wav_input=silence_input(tmp_path, seconds=SILENCE_SEC, realtime=True),
    )
    api = app.start_api()

    # 実行
    elapsed_list = _run_cycles(api, receiver, CYCLES)

    # 検証
    ordered = sorted(elapsed_list)
    print(  # noqa: T201 測った値を実行の出力に残す
        f"api_start_response_time: n={len(ordered)} min={ordered[0]:.1f} "
        f"p50={ordered[len(ordered) // 2]:.1f} max={ordered[-1]:.1f} ms"
    )
    assert len(receiver.received) == CYCLES
    assert len({payload["session_id"] for payload in receiver.received}) == CYCLES
    assert all(payload["result"] == "transcribed" for payload in receiver.received)
    assert max(elapsed_list) <= RESPONSE_LIMIT_MS
