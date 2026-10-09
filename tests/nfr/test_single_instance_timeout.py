"""前の常駐サービスの終わりを待つ時間（single_instance_timeout）の非機能要件テスト。

固めた設定（tests/nfr/fixtures/whisper.env の large-v3・cuda）で `python -m voice_paste --data-dir {一時フォルダ}` を
起動し、同じ `--data-dir` でもう 1 つ起動して、後のプロセスのログの「前の常駐サービスに終わるよう頼んだ」から
「単一インスタンスを確保した」までの時間を測る。前のプロセスが待機中のとき（10 回）と、モデルの読み込み中のとき（5 回）。
`--run-e2e` が無い環境・固めた設定が無い環境・GPU が無い環境では skip する。
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from tests.integration.helpers import wait_until
from tests.support.instances import (
    service_root_count,
    wait_for_acquired,
    wait_for_takeover,
)
from tests.support.real_service import RealService, spawn_process
from tests.support.resident_app import kill_service_processes_for
from tests.support.whisper_fixtures import local_whisper_toml, requires_real_whisper

pytestmark = [pytest.mark.real_machine, requires_real_whisper]

PREVIOUS_RUNNING_CYCLES = 10
"""前のプロセスが待機中のときに入れ替える回数。"""

PREVIOUS_STARTING_CYCLES = 5
"""前のプロセスがモデルの読み込み中のときに入れ替える回数。"""

WAIT_LIMIT_SEC = 54.0
"""前の常駐サービスの終わりを待つ時間の決定値（秒）。"""

PREVIOUS_EXIT_TIMEOUT_SEC = 10.0
"""後のプロセスが立ち上がった後、前のプロセスの終わりを確かめるまで待つ上限。"""

ACQUIRE_TIMEOUT_SEC = 60.0
"""前のプロセスが排他を取るまで（起動の初め）待つ上限。"""


def _replace_once(data_dir: Path, *, previous_starting: bool) -> float:
    """前のプロセスを起動し、同じ置き場所で後のプロセスを起動して入れ替わるまでを確かめ、待った秒数を返す。

    previous_starting が True なら、前のプロセスが排他を取った直後（モデルの読み込み中）に後のプロセスを起動する。
    """
    # 準備: 前のプロセスを起動する（待機中を待つか、排他を取っただけで次へ進むか）
    first = RealService.launch(
        data_dir, extra_settings=local_whisper_toml(), wait_for_api=not previous_starting
    )
    try:
        if previous_starting:
            wait_for_acquired(data_dir, first.process, ACQUIRE_TIMEOUT_SEC)

        # 実行: 同じ置き場所で後のプロセスを起動し、入れ替わって立ち上がるまで待つ
        second = spawn_process(data_dir, stdout_name="stdout_second.log")
        takeover = wait_for_takeover(data_dir, second)

        # 検証: 前のプロセスが終わり（終了コード 0）、常駐サービスが 1 つだけ動き、後のプロセスは動いている
        assert wait_until(lambda: not first.is_running(), PREVIOUS_EXIT_TIMEOUT_SEC), (
            "前の常駐サービスが終わらなかった"
        )
        assert first.process.returncode == 0
        assert second.poll() is None
        assert service_root_count(data_dir) == 1
        return takeover.wait_sec
    finally:
        first.shutdown()
        kill_service_processes_for(data_dir)


def _report(name: str, waits: list[float]) -> None:
    """測った生の値と中央値・最大を実行の出力に残す。"""
    print(  # noqa: T201 測った値を実行の出力に残す
        f"{name}: n={len(waits)} raw={[round(v, 2) for v in waits]} "
        f"median={statistics.median(waits):.2f} max={max(waits):.2f} sec"
    )


def test_single_instance_timeout(tmp_path: Path) -> None:
    """常駐中に同じ置き場所でもう 1 つ起動すると、前の常駐サービスが終わり、決定値以内に後のプロセスが排他を取る（実機）。"""
    # 実行: 前のプロセスが待機中の状態から、10 回入れ替える
    waits = [
        _replace_once(tmp_path / f"run{index:02d}", previous_starting=False)
        for index in range(PREVIOUS_RUNNING_CYCLES)
    ]

    # 検証
    _report("single_instance_timeout", waits)
    assert len(waits) == PREVIOUS_RUNNING_CYCLES
    assert max(waits) <= WAIT_LIMIT_SEC


def test_single_instance_timeout_when_previous_starting(tmp_path: Path) -> None:
    """前の常駐サービスがモデルの読み込み中でも、決定値以内に入れ替わり、常駐サービスが 0 個にならない（実機）。"""
    # 実行: 前のプロセスが排他を取った直後（モデルの読み込み中）から、5 回入れ替える
    waits = [
        _replace_once(tmp_path / f"run{index:02d}", previous_starting=True)
        for index in range(PREVIOUS_STARTING_CYCLES)
    ]

    # 検証
    _report("single_instance_timeout_when_previous_starting", waits)
    assert len(waits) == PREVIOUS_STARTING_CYCLES
    assert max(waits) <= WAIT_LIMIT_SEC
