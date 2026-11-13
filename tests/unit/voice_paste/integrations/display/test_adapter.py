"""integrations/display/adapter.py（inhibit_display・release_display）の単体テスト。

kernel32 は、電源要求の関数の呼び出しを記録する偽物に差し替える（_kernel32 を差し替える）。
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

from voice_paste.shared.errors import DisplayInhibitError

# ctypes の Win32 を読み込むアダプタのため、Linux では流さない
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="電源要求のアダプタは Windows でだけ流す"
)

HANDLE = 0x1234
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
POWER_REQUEST_DISPLAY_REQUIRED = 0
POWER_REQUEST_SYSTEM_REQUIRED = 1


class FakeKernel32:
    """kernel32 の偽物。電源要求の関数の呼び出しを順に覚え、失敗を返すかを切り替えられる。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.create_result: int | None = HANDLE
        # 0 を返す回（何回目の呼び出しか。1 始まり）
        self.set_fail_on: int | None = None
        self.clear_fail_on: int | None = None
        self._set_count = 0
        self._clear_count = 0

    def PowerCreateRequest(self, reason: object) -> int | None:  # noqa: N802 Win32 の名前に合わせる
        """電源要求を作ったことを覚え、create_result を返す。"""
        self.calls.append(("PowerCreateRequest", ()))
        return self.create_result

    def PowerSetRequest(self, handle: int, kind: int) -> int:  # noqa: N802 Win32 の名前に合わせる
        """要求を設定したことを覚え、set_fail_on の回だけ 0 を返す。"""
        self._set_count += 1
        self.calls.append(("PowerSetRequest", (handle, kind)))
        return 0 if self._set_count == self.set_fail_on else 1

    def PowerClearRequest(self, handle: int, kind: int) -> int:  # noqa: N802 Win32 の名前に合わせる
        """要求を解いたことを覚え、clear_fail_on の回だけ 0 を返す。"""
        self._clear_count += 1
        self.calls.append(("PowerClearRequest", (handle, kind)))
        return 0 if self._clear_count == self.clear_fail_on else 1

    def CloseHandle(self, handle: int) -> int:  # noqa: N802 Win32 の名前に合わせる
        """ハンドルを閉じたことを覚える。"""
        self.calls.append(("CloseHandle", (handle,)))
        return 1

    def names(self) -> list[str]:
        """呼ばれた関数の名前を順に返す。"""
        return [name for name, _ in self.calls]


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleType, FakeKernel32]]:
    """偽の kernel32 を差し替え、抑止していない状態のアダプタのモジュールを返す。"""
    from voice_paste.integrations.display import adapter as module

    kernel32 = FakeKernel32()
    monkeypatch.setattr(module, "_kernel32", lambda: kernel32)
    monkeypatch.setattr(module, "_handle", None)
    yield module, kernel32


def test_inhibit_display(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """電源要求を作って 2 つの種類を設定する（正常系）。"""
    # 準備
    module, kernel32 = adapter

    # 実行
    module.inhibit_display()

    # 検証
    set_calls = [args for name, args in kernel32.calls if name == "PowerSetRequest"]
    assert set_calls == [
        (HANDLE, POWER_REQUEST_DISPLAY_REQUIRED),
        (HANDLE, POWER_REQUEST_SYSTEM_REQUIRED),
    ]
    assert "PowerClearRequest" not in kernel32.names()


def test_inhibit_display_when_already_inhibited(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """抑止中にもう一度呼んでも電源要求を作り直さない（正常系）。"""
    # 準備
    module, kernel32 = adapter

    # 実行
    module.inhibit_display()
    module.inhibit_display()

    # 検証
    assert kernel32.names().count("PowerCreateRequest") == 1


def test_inhibit_display_when_create_failed(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """電源要求を作れなければ DisplayInhibitError（異常系）。"""
    # 準備
    module, kernel32 = adapter
    kernel32.create_result = INVALID_HANDLE_VALUE

    # 実行・検証
    with pytest.raises(DisplayInhibitError):
        module.inhibit_display()
    assert "PowerSetRequest" not in kernel32.names()

    # 続く解除は何もしない
    module.release_display()
    assert "PowerClearRequest" not in kernel32.names()


def test_inhibit_display_when_set_failed(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """種類を設定できなければ設定した分を解いてハンドルを閉じる（異常系）。"""
    # 準備
    module, kernel32 = adapter
    kernel32.set_fail_on = 2

    # 実行・検証
    with pytest.raises(DisplayInhibitError):
        module.inhibit_display()
    clear_calls = [args for name, args in kernel32.calls if name == "PowerClearRequest"]
    assert clear_calls == [(HANDLE, POWER_REQUEST_DISPLAY_REQUIRED)]
    assert kernel32.names().count("CloseHandle") == 1


def test_release_display(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """2 つの種類を解いてハンドルを閉じる（正常系）。"""
    # 準備
    module, kernel32 = adapter
    module.inhibit_display()

    # 実行
    module.release_display()
    module.release_display()

    # 検証
    clear_calls = [args for name, args in kernel32.calls if name == "PowerClearRequest"]
    assert clear_calls == [
        (HANDLE, POWER_REQUEST_DISPLAY_REQUIRED),
        (HANDLE, POWER_REQUEST_SYSTEM_REQUIRED),
    ]
    assert kernel32.names().count("CloseHandle") == 1


def test_release_display_when_not_inhibited(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """抑止していなければ何もしない（正常系）。"""
    # 準備
    module, kernel32 = adapter

    # 実行
    module.release_display()

    # 検証
    assert kernel32.calls == []


def test_release_display_when_clear_failed(adapter: tuple[ModuleType, FakeKernel32]) -> None:
    """解けなくてもハンドルを閉じて手放す（異常系）。"""
    # 準備
    module, kernel32 = adapter
    module.inhibit_display()
    kernel32.clear_fail_on = 1

    # 実行・検証
    with pytest.raises(DisplayInhibitError):
        module.release_display()
    assert kernel32.names().count("CloseHandle") == 1

    # 続く抑止は新しい電源要求を作る
    module.inhibit_display()
    assert kernel32.names().count("PowerCreateRequest") == 2
