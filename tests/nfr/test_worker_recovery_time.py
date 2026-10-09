"""文字起こしワーカーの立て直しの時間（worker_recovery_time）の非機能要件テスト。

固めた設定（tests/nfr/fixtures/whisper.env の large-v3・cuda）で WhisperWorkerClient を作り、
start → stop を 20 回続けて、ワーカーの起動から ready を受けるまでの時間を測る。
`--run-e2e` が無い環境・固めた設定が無い環境・GPU が無い環境では skip する。
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from tests.support.whisper_fixtures import (
    WORKER_READY_TIMEOUT_SEC,
    WORKER_STOP_TIMEOUT_SEC,
    load_local_whisper_settings,
    requires_real_whisper,
)

pytestmark = [pytest.mark.real_machine, requires_real_whisper]

CYCLES = 20
"""start → stop を続ける回数。"""

MEASURE_LIMIT_SEC = WORKER_READY_TIMEOUT_SEC
"""ワーカーの起動から ready までの決定値（秒）。"""


def test_worker_recovery_time(tmp_path: Path) -> None:
    """新しい構成のワーカーの起動からモデルの読み込みが終わるまでが決定値以内である（実機）。"""
    from voice_paste.integrations.whisper.client import WhisperWorkerClient

    # 準備
    client = WhisperWorkerClient(
        settings=load_local_whisper_settings(),
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=tmp_path,
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
    )
    elapsed_list: list[float] = []

    # 実行: 毎回の start（起動から ready を受けるまで。ready を受けられなければ例外）の時間を測り、止める
    for _ in range(CYCLES):
        started = time.perf_counter()
        client.start()
        elapsed_list.append(time.perf_counter() - started)
        client.stop()

    # 検証
    print(  # noqa: T201 測った値を実行の出力に残す
        f"worker_recovery_time: n={len(elapsed_list)} raw={[round(v, 2) for v in elapsed_list]} "
        f"median={statistics.median(elapsed_list):.2f} max={max(elapsed_list):.2f} sec"
    )
    assert len(elapsed_list) == CYCLES
    assert max(elapsed_list) <= MEASURE_LIMIT_SEC
