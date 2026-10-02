"""runtime/process.py（relaunch）の単体テスト。

subprocess.Popen は偽物に差し替え、実際にプロセスを起動しない。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

ARGV = ["--data-dir", "C:/tmp/vp"]


def test_relaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    """同じ引数で切り離して起動する（正常系）。"""
    from voice_paste.runtime.process import relaunch

    # 準備
    popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen)

    # 実行
    relaunch(ARGV)

    # 検証
    popen.assert_called_once()
    assert popen.call_args.args[0] == [sys.executable, "-m", "voice_paste", *ARGV]
    assert popen.call_args.kwargs["creationflags"] & subprocess.DETACHED_PROCESS
    assert popen.call_args.kwargs["close_fds"] is True


def test_relaunch_when_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """起動できなくても例外を漏らさない（異常系）。"""
    from voice_paste.runtime.process import relaunch

    # 準備
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=OSError("起動できない")))

    # 実行
    relaunch(ARGV)

    # 検証
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1
