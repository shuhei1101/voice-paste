"""文字起こしワーカーの終わりを待つ時間（worker_stop_timeout）の非機能要件テスト。

固めた設定（tests/nfr/fixtures/whisper.env の large-v3・cuda）で WhisperWorkerClient を start しては
標準入力を閉じることを 20 回続け、標準入力を閉じてからワーカーのプロセスが終わるまでの時間を測る。
`--run-e2e` が無い環境・固めた設定が無い環境・GPU が無い環境では skip する。
"""

from __future__ import annotations

import statistics
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.support.whisper_fixtures import (
    WORKER_READY_TIMEOUT_SEC,
    WORKER_STOP_TIMEOUT_SEC,
    load_local_whisper_settings,
    requires_real_whisper,
)

if TYPE_CHECKING:
    from voice_paste.integrations.whisper.client import WhisperWorkerClient

pytestmark = [pytest.mark.real_machine, requires_real_whisper]

CYCLES = 20
"""start → 標準入力を閉じる を続ける回数。"""

STOP_LIMIT_SEC = WORKER_STOP_TIMEOUT_SEC
"""標準入力を閉じてからワーカーが終わるまでの決定値（秒）。"""


def _measure_stop(client: WhisperWorkerClient) -> float:
    """ワーカーの標準入力を閉じてから、プロセスが終わるまでの秒数を返す。決定値までに終わらなければ TimeoutExpired。"""
    # 窓口が持つ子プロセス（stop が閉じるものと同じ）を直に取り、terminate を挟まずに終わるまでを測る
    process: subprocess.Popen[str] | None = client._process
    assert process is not None
    assert process.stdin is not None
    started = time.perf_counter()
    process.stdin.close()
    process.wait(timeout=STOP_LIMIT_SEC)
    return time.perf_counter() - started


def test_worker_stop_timeout(tmp_path: Path) -> None:
    """モデルを読み込んだワーカーが、標準入力を閉じてから決定値以内に終わる（実機）。"""
    from voice_paste.integrations.whisper.client import WhisperWorkerClient

    # 準備
    client = WhisperWorkerClient(
        settings=load_local_whisper_settings(),
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=tmp_path,
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
    )
    elapsed_list: list[float] = []

    # 実行: 毎回 start（ready まで）し、標準入力を閉じてから終わるまでを測る（terminate は使わない）
    for _ in range(CYCLES):
        client.start()
        elapsed_list.append(_measure_stop(client))
        # 終わったワーカーの後始末（窓口の状態を戻す）
        client.stop()

    # 検証: 20 回とも terminate せずに決定値以内に終わった（超えていれば _measure_stop が失敗する）
    print(  # noqa: T201 測った値を実行の出力に残す
        f"worker_stop_timeout: n={len(elapsed_list)} raw={[round(v, 2) for v in elapsed_list]} "
        f"median={statistics.median(elapsed_list):.2f} max={max(elapsed_list):.2f} sec"
    )
    assert len(elapsed_list) == CYCLES
    assert max(elapsed_list) <= STOP_LIMIT_SEC
