"""処理中の開始へのエラーの応答時間（busy_response_time）の非機能要件テスト。

本物の常駐サービス（実機のマイク）で API のセッションを処理中にしたまま、開始を続けて呼び、
409 が決定値以内に返り、2 つ目の録音が始まらないことを測る。
ホットキーの受付はまだ新しい構成に無いため、処理中は API で始めたセッションにする。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.fixtures import receiver, start_service  # noqa: F401 フィクスチャとして使う
from tests.support.real_service import RealService

pytestmark = pytest.mark.real_machine

TRIALS = 20
"""処理中の開始を呼ぶ回数。"""

RESPONSE_LIMIT_MS = 1000
"""処理中の開始へのエラーの応答時間の決定値（ミリ秒）。"""

RECORD_SEC = 0.5
RECEIVE_TIMEOUT_SEC = 30.0
SESSION_START_LOG = "セッションを始めた"
"""セッションを始めたときのログの言葉。"""

NO_SPEECH_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も音声とみなさない設定。"""


def _call_busy(service: RealService, receiver: CallbackReceiver, trials: int) -> list[tuple[int, float]]:
    """処理中の開始を trials 回呼び、毎回のステータスと応答時間（ミリ秒）を並べて返す。"""
    results: list[tuple[int, float]] = []
    for _ in range(trials):
        response, elapsed_ms = service.start_session(receiver.url)
        results.append((response.status_code, elapsed_ms))
    return results


def test_busy_response_time(
    start_service: Callable[..., RealService], receiver: CallbackReceiver  # noqa: F811
) -> None:
    """処理中に開始を呼ぶと 409 が決定値以内に返り、2 つ目の録音が始まらない（実機）。"""
    # 準備
    service = start_service(NO_SPEECH_SETTINGS)
    response, _elapsed_ms = service.start_session(receiver.url)
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    # 実行
    results = _call_busy(service, receiver, TRIALS)

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
    assert service.post(f"/sessions/{session_id}/stop").status_code == 200
    assert service.post(f"/sessions/{session_id}/complete").status_code == 202
    assert wait_until(lambda: len(receiver.received) >= 1, RECEIVE_TIMEOUT_SEC)
    started = [record for record in service.log_records() if SESSION_START_LOG in record["msg"]]
    assert len(started) == 1
