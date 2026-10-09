"""同じ置き場所で続けて起動した常駐サービスの入れ替えを、ログから観測する補助（E2E・実機の非機能要件テスト用）。

後から起動したプロセスは、前のプロセスに終わるよう頼み（「前の常駐サービスに終わるよう頼んだ」）、排他を取り
（「単一インスタンスを確保した」）、立ち上がる（「常駐サービスを始めた」）。同じ置き場所のログには前のプロセスの
行も混ざるため、後のプロセスの行は「頼んだ」の行より後に出た行として数える。
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.support.real_service import POLL_SEC, read_log_records
from tests.support.resident_app import service_processes_for

ASKED_MESSAGE = "前の常駐サービスに終わるよう頼んだ"
"""後のプロセスが、前のプロセスの終了の依頼を立てたときのログの文。"""

ACQUIRED_PREFIX = "単一インスタンスを確保した"
"""排他を取ったときのログの文の先頭。"""

STARTED_PREFIX = "常駐サービスを始めた"
"""API・ホットキー・トレイを立て終えたときのログの文の先頭。"""

TAKEOVER_TIMEOUT_SEC = 120.0
"""後のプロセスが立ち上がるまで待つ上限（前のプロセスの終わりを待つ上限とモデルの読み込みを含む）。"""

LOG_TAIL_RECORDS = 15
"""待ちきれなかったときに、失敗の説明へ添えるログの行数。"""


@dataclass(frozen=True)
class Takeover:
    """後のプロセスが前のプロセスと入れ替わった時刻。"""

    asked_at: datetime
    """前のプロセスに終わるよう頼んだ時刻。"""

    acquired_at: datetime
    """排他を取った時刻。"""

    started_at: datetime
    """立ち上がった時刻。"""

    @property
    def wait_sec(self) -> float:
        """終わるよう頼んでから排他を取れるまでの秒数。"""
        return (self.acquired_at - self.asked_at).total_seconds()


def _find_takeover(records: list[dict[str, Any]]) -> Takeover | None:
    """ログの行を書かれた順に見て、「頼んだ」の後の「確保した」と、その後の「始めた」の時刻を探す。無ければ None。"""
    asked_at: datetime | None = None
    acquired_at: datetime | None = None
    for record in records:
        message = str(record["msg"])
        timestamp = datetime.fromisoformat(record["ts"])
        # 頼んだ行より前は、前のプロセスの行
        if asked_at is None:
            if message == ASKED_MESSAGE:
                asked_at = timestamp
        elif acquired_at is None:
            if message.startswith(ACQUIRED_PREFIX):
                acquired_at = timestamp
        elif message.startswith(STARTED_PREFIX):
            return Takeover(asked_at=asked_at, acquired_at=acquired_at, started_at=timestamp)
    return None


def wait_for_takeover(
    data_dir: Path,
    process: subprocess.Popen[bytes],
    timeout_sec: float = TAKEOVER_TIMEOUT_SEC,
) -> Takeover:
    """後から起動した process が、前のプロセスと入れ替わって立ち上がるまで待ち、その時刻を返す。

    process が先に終わったか、timeout_sec までに立ち上がらなければ、ログの終わりを添えて RuntimeError にする。
    """
    deadline = time.monotonic() + timeout_sec
    while True:
        records = read_log_records(data_dir)
        takeover = _find_takeover(records)
        if takeover is not None:
            return takeover
        if process.poll() is not None or time.monotonic() > deadline:
            tail = "\n".join(
                f"{record['ts']} {record['level']} {record['msg']}"
                for record in records[-LOG_TAIL_RECORDS:]
            )
            state = "終わった" if process.poll() is not None else "立ち上がらなかった"
            raise RuntimeError(f"後から起動したプロセスが入れ替われずに{state}:\n{tail}")
        time.sleep(POLL_SEC)


def wait_for_acquired(data_dir: Path, process: subprocess.Popen[bytes], timeout_sec: float) -> None:
    """最初に起動した process が排他を取った（ログに「単一インスタンスを確保した」が出た）のを待つ。取れなければ RuntimeError。"""
    deadline = time.monotonic() + timeout_sec
    while not any(
        str(record["msg"]).startswith(ACQUIRED_PREFIX) for record in read_log_records(data_dir)
    ):
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("最初に起動したプロセスが排他を取れなかった")
        time.sleep(POLL_SEC)


def started_count(data_dir: Path) -> int:
    """data_dir のログに「常駐サービスを始めた」が書かれた回数を返す（再起動で起動し直したプロセスの分を含む）。"""
    return sum(
        str(record["msg"]).startswith(STARTED_PREFIX) for record in read_log_records(data_dir)
    )


def service_root_count(data_dir: Path) -> int:
    """data_dir で動いている常駐サービスの数を返す（venv の python.exe は本体を子に持つため、親が同じ一覧に無いものを数える）。"""
    processes = service_processes_for(data_dir)
    pids = {process.pid for process in processes}
    return sum(1 for process in processes if process.parent_pid not in pids)
