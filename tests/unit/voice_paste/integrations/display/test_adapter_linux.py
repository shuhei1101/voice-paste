"""integrations/display/adapter_linux.py（inhibit_display_linux・release_display_linux）の単体テスト。

subprocess.Popen は、起動の引数と子プロセスへの操作を記録する偽物に差し替える。
実物の gnome-session-inhibit は検証環境の VM での通しの確認で確かめる。
"""

from __future__ import annotations

import io
import logging
import subprocess
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest

from voice_paste.shared.errors import DisplayInhibitError


class FakeStdin:
    """子プロセスの標準入力の偽物。閉じたことを覚える。"""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def close(self) -> None:
        """閉じたことを覚える。"""
        self._events.append("stdin.close")


class FakeProcess:
    """subprocess.Popen の偽物。poll・wait・kill を覚え、先に終わっていたか・待ちが切れるかを切り替えられる。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stdin = FakeStdin(events)
        self.stderr = io.BytesIO(b"")
        self.returncode: int | None = None
        # 初回の wait で TimeoutExpired を送出するか
        self.timeout_once = False

    def poll(self) -> int | None:
        """終わっていれば終了コードを返す。"""
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        """待ったことを覚え、timeout_once なら初回だけ待ちが切れる。"""
        self.events.append(f"wait({timeout})")
        if self.timeout_once:
            self.timeout_once = False
            raise subprocess.TimeoutExpired("gnome-session-inhibit", timeout or 0)
        self.returncode = 0
        return 0

    def kill(self) -> None:
        """強制終了したことを覚える。"""
        self.events.append("kill")


class PopenRecorder:
    """subprocess.Popen の代わりに呼ばれ、起動の引数を覚えて偽の子プロセスを返す。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.events: list[str] = []
        self.error: Exception | None = None
        self.process = FakeProcess(self.events)

    def __call__(self, *args: Any, **kwargs: Any) -> FakeProcess:
        """起動の引数を覚え、error があれば送出する。"""
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.process


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleType, PopenRecorder]]:
    """偽の Popen を差し替え、抑止していない状態のアダプタのモジュールを返す。"""
    from voice_paste.integrations.display import adapter_linux as module

    popen = PopenRecorder()
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "_process", None)
    yield module, popen


def test_inhibit_display_linux(adapter: tuple[ModuleType, PopenRecorder]) -> None:
    """標準入力をパイプにして子プロセスを起動する（正常系）。"""
    # 準備
    module, popen = adapter

    # 実行
    module.inhibit_display_linux()

    # 検証
    args, kwargs = popen.calls[0]
    assert tuple(args[0]) == module.INHIBIT_COMMAND
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE


def test_inhibit_display_linux_when_already_inhibited(
    adapter: tuple[ModuleType, PopenRecorder],
) -> None:
    """抑止中にもう一度呼んでも子プロセスを増やさない（正常系）。"""
    # 準備
    module, popen = adapter

    # 実行
    module.inhibit_display_linux()
    module.inhibit_display_linux()

    # 検証
    assert len(popen.calls) == 1


def test_inhibit_display_linux_when_command_missing(
    adapter: tuple[ModuleType, PopenRecorder],
) -> None:
    """gnome-session-inhibit が無ければ DisplayInhibitError（異常系）。"""
    # 準備
    module, popen = adapter
    popen.error = FileNotFoundError("gnome-session-inhibit")

    # 実行・検証
    with pytest.raises(DisplayInhibitError):
        module.inhibit_display_linux()

    # 続く解除は何もしない
    module.release_display_linux()
    assert popen.events == []


def test_release_display_linux(adapter: tuple[ModuleType, PopenRecorder]) -> None:
    """標準入力を閉じて子プロセスの終わりを待つ（正常系）。"""
    # 準備
    module, popen = adapter
    module.inhibit_display_linux()

    # 実行
    module.release_display_linux()
    module.release_display_linux()

    # 検証
    assert popen.events == ["stdin.close", f"wait({module.RELEASE_WAIT_SEC})"]


def test_release_display_linux_when_not_inhibited(
    adapter: tuple[ModuleType, PopenRecorder],
) -> None:
    """抑止していなければ何もしない（正常系）。"""
    # 準備
    module, popen = adapter

    # 実行
    module.release_display_linux()

    # 検証
    assert popen.events == []


def test_release_display_linux_when_exited_early(
    adapter: tuple[ModuleType, PopenRecorder],
) -> None:
    """子プロセスが先に終わっていれば、抑止できていなかったとして DisplayInhibitError（異常系）。"""
    # 準備
    module, popen = adapter
    module.inhibit_display_linux()
    popen.process.returncode = 1
    popen.process.stderr = io.BytesIO(b"Failed to inhibit: no session")

    # 実行・検証
    with pytest.raises(DisplayInhibitError) as exc_info:
        module.release_display_linux()
    assert "1" in str(exc_info.value)
    assert "Failed to inhibit" in str(exc_info.value)
    assert "stdin.close" not in popen.events
    assert "kill" not in popen.events

    # 続く解除は何もしない
    module.release_display_linux()
    assert popen.events == []


def test_release_display_linux_when_timeout(
    adapter: tuple[ModuleType, PopenRecorder], caplog: pytest.LogCaptureFixture
) -> None:
    """終わらなければ強制終了する（正常系）。"""
    # 準備
    module, popen = adapter
    module.inhibit_display_linux()
    popen.process.timeout_once = True

    # 実行
    with caplog.at_level(logging.WARNING):
        module.release_display_linux()

    # 検証
    assert popen.events.count("kill") == 1
    assert "強制終了" in caplog.text
