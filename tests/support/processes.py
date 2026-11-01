"""実機のテスト（E2E・実機の非機能要件テスト）が使う、プロセスの一覧と終了の補助。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from collections.abc import Iterable
from dataclasses import dataclass

POWERSHELL_TIMEOUT_SEC = 30.0


@dataclass(frozen=True)
class ProcessInfo:
    """プロセスの 1 行（番号・親・コマンドライン）。"""

    pid: int
    parent_pid: int
    command_line: str


def _proc_table() -> list[ProcessInfo]:
    """全てのプロセスを /proc から引く（Linux。PoC）。"""
    rows: list[ProcessInfo] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            continue
        # comm は括弧に囲まれ空白を含みうるため、最後の ')' の後ろから読む
        parent = int(stat[stat.rindex(")") + 2 :].split()[1])
        rows.append(ProcessInfo(int(entry.name), parent, command))
    return rows


def process_table() -> list[ProcessInfo]:
    """全てのプロセスを PowerShell（Get-CimInstance）で引く。"""
    if sys.platform != "win32":
        return _proc_table()
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(  # noqa: S603 固定のコマンド
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=POWERSHELL_TIMEOUT_SEC,
        check=True,
    )
    rows = json.loads(result.stdout)
    return [
        ProcessInfo(int(row["ProcessId"]), int(row["ParentProcessId"]), row["CommandLine"] or "")
        for row in rows
    ]


def descendants(root_pid: int, table: Iterable[ProcessInfo] | None = None) -> list[ProcessInfo]:
    """root_pid とその子孫のプロセスを返す（venv の python.exe は本体のプロセスを子に持つため、子孫まで辿る）。"""
    rows = list(table) if table is not None else process_table()
    found = {root_pid}
    result: list[ProcessInfo] = []
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row.pid in found and row not in result:
                result.append(row)
            if row.parent_pid in found and row.pid not in found:
                found.add(row.pid)
                changed = True
    return result


def kill_tree(pid: int) -> None:
    """プロセスと子孫を止める。"""
    if sys.platform != "win32":
        for process in reversed(descendants(pid)):
            try:
                os.kill(process.pid, signal.SIGKILL)
            except OSError:
                continue
        return
    subprocess.run(  # noqa: S603 固定のコマンド
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False
    )


def processes_with(command_fragment: str, tree_root_pid: int) -> list[ProcessInfo]:
    """tree_root_pid の子孫のうち、コマンドラインに command_fragment を含むプロセスを返す。"""
    return [p for p in descendants(tree_root_pid) if command_fragment in p.command_line]
