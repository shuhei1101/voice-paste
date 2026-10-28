"""runtime/process.py（relaunch）の単体テスト。

subprocess.Popen は偽物に差し替え、実際にプロセスを起動しない。
Windows の切り離しのフラグ（DETACHED_PROCESS）は Linux の subprocess に属性が無いため、process.py の定数で確かめる。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

ARGV = ["--data-dir", "C:/tmp/vp"]
LINUX_ARGV = ["--data-dir", "/tmp/vp"]


def test_relaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows では同じ引数で切り離して起動する（正常系）。"""
    from voice_paste.runtime.process import DETACHED_PROCESS, relaunch
    from voice_paste.shared.os_kind import OsKind

    # 準備
    popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen)

    # 実行
    relaunch(ARGV, os_kind=OsKind.WINDOWS)

    # 検証
    popen.assert_called_once()
    assert popen.call_args.args[0] == [sys.executable, "-m", "voice_paste", *ARGV]
    assert popen.call_args.kwargs["creationflags"] & DETACHED_PROCESS
    assert popen.call_args.kwargs["close_fds"] is True


def test_relaunch_when_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux では新しいセッションで起動する（正常系）。"""
    from voice_paste.runtime.process import relaunch
    from voice_paste.shared.os_kind import OsKind

    # 準備
    popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen)

    # 実行
    relaunch(LINUX_ARGV, os_kind=OsKind.LINUX)

    # 検証
    popen.assert_called_once()
    assert popen.call_args.args[0] == [sys.executable, "-m", "voice_paste", *LINUX_ARGV]
    assert popen.call_args.kwargs["start_new_session"] is True
    assert "creationflags" not in popen.call_args.kwargs


def test_relaunch_when_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """起動できなくても例外を漏らさない（異常系）。"""
    from voice_paste.runtime.process import relaunch
    from voice_paste.shared.os_kind import OsKind

    # 準備
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=OSError("起動できない")))

    # 実行
    relaunch(ARGV, os_kind=OsKind.WINDOWS)

    # 検証
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1
