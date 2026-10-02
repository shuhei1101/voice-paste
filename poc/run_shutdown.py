"""PoC のアプリを別のプロセスグループで立て、Ctrl+Break とトレイの「終了」での終わり方を測る。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RUNS_PER_CASE = 3
READY_TIMEOUT_SEC = 30.0
EXIT_TIMEOUT_SEC = 30.0
POLL_SEC = 0.05
TRAY_QUIT_AFTER_MS = 1500
WAKE_MS = 200


def run_once(out: Path, *, by: str, wake_ms: int, no_tick: bool) -> dict[str, object]:
    """1 回立てて終わらせ、終わるまでの秒数と終了コードを返す。"""
    for path in (Path(f"{out}.ready"), Path(f"{out}.shutdown.json")):
        path.unlink(missing_ok=True)
    args = [sys.executable, str(Path(__file__).with_name("qt_threads.py")), "--out", str(out), "--idle"]
    args += ["--wake-ms", str(wake_ms)]
    # 表示のタイマーも無い（Python へ戻る契機が無い）状態を測るときは止める
    if no_tick:
        args.append("--no-tick")
    # トレイの「終了」で終わらせるときは、準備ができた後にアプリ自身が選ぶ
    if by == "tray":
        args += ["--tray-quit-after-ms", str(TRAY_QUIT_AFTER_MS)]
    process = subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    deadline = time.monotonic() + READY_TIMEOUT_SEC
    while not Path(f"{out}.ready").exists() and time.monotonic() < deadline:
        time.sleep(POLL_SEC)
    # Ctrl+Break で終わらせるときは、E2E の後始末と同じく CTRL_BREAK_EVENT を送る
    if by == "break":
        sent_at = time.time()
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    try:
        process.wait(timeout=EXIT_TIMEOUT_SEC)
        killed = False
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        killed = True
    exited_at = time.time()
    shutdown_path = Path(f"{out}.shutdown.json")
    shutdown = json.loads(shutdown_path.read_text(encoding="utf-8")) if shutdown_path.exists() else {}
    if by == "tray":
        sent_at = shutdown.get("tray_quit_at", exited_at)
    return {
        "by": by,
        "wake_ms": wake_ms,
        "no_tick": no_tick,
        "exit_sec": round(exited_at - sent_at, 3),
        "returncode": process.returncode,
        "killed": killed,
        "threads_alive": shutdown.get("threads_alive"),
    }


def main() -> int:
    """終わらせ方とタイマーの有無の組ごとに 3 回測り、結果を JSON に書く。"""
    out = Path(sys.argv[1])
    results = [
        run_once(out, by=by, wake_ms=wake_ms, no_tick=no_tick)
        for by, wake_ms, no_tick in (
            ("break", 0, False),
            ("break", WAKE_MS, False),
            ("break", 0, True),
            ("break", WAKE_MS, True),
            ("tray", 0, False),
        )
        for _ in range(RUNS_PER_CASE)
    ]
    Path(f"{out}.runs.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())