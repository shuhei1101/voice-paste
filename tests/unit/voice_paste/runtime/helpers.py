"""単一インスタンスの単体テスト用の Win32 の道具と、別のスレッドで排他を取る補助。

名前付きのミューテックスは取ったスレッドだけが放せ、同じスレッドからは何度でも取れてしまう。
そのため、ほかの持ち主がいる状況や放した後の取り直しは、別のスレッドで取って確かめる。
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voice_paste.runtime.single_instance import SingleInstanceLock

EVENT_MODIFY_STATE: int = 0x0002
"""イベントを立てる権限。"""

SYNCHRONIZE: int = 0x00100000
"""イベントを待つ権限。"""

WAIT_OBJECT_0: int = 0
"""WaitForSingleObject が、待っていたものが立ったと返す値。"""

OTHER_PROCESS_WAIT_MS: int = 10_000
"""前の持ち主を模すスレッドが、終了の依頼を待つ上限（ミリ秒）。テストが失敗してもスレッドが残らないようにする。"""

JOIN_TIMEOUT_SEC: float = 15.0
"""テストが起こしたスレッドの終わりを待つ上限。"""

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD


def mutex_name(name: str) -> str:
    """排他の名前から、名前付きのミューテックスの名前を作る。"""
    return f"Local\\{name}"


def quit_event_name(name: str) -> str:
    """排他の名前から、終了の依頼の名前付きのイベントの名前を作る。"""
    return f"Local\\{name}-quit"


def open_quit_event(name: str) -> int:
    """終了の依頼の名前付きのイベントを、立てる権限で開いてハンドルを返す。開けなければ OSError。"""
    handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, quit_event_name(name))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def set_event(handle: int) -> None:
    """イベントを立てる。"""
    if not _kernel32.SetEvent(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def close_handle(handle: int) -> None:
    """ハンドルを閉じる。"""
    _kernel32.CloseHandle(handle)


def request_quit(name: str) -> None:
    """後から起動したプロセスの代わりに、終了の依頼のイベントを 1 回立てる。"""
    handle = open_quit_event(name)
    set_event(handle)
    close_handle(handle)


class BackgroundAcquire:
    """別のスレッドで acquire_single_instance を呼び、取れたロックか取れなかった理由を控える。

    取れたロックは、finish が呼ばれたらそのスレッドで放す（ミューテックスは取ったスレッドで放すため）。
    """

    def __init__(self, name: str, timeout_sec: float) -> None:
        # テストのスレッドで import し、実装が無いときはそのテストが ImportError で落ちるようにする
        from voice_paste.runtime.single_instance import acquire_single_instance

        self._acquire = acquire_single_instance
        self._name = name
        self._timeout_sec = timeout_sec
        self.lock: SingleInstanceLock | None = None
        self.error: Exception | None = None
        self._done = threading.Event()
        self._finish = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """排他を取り、取れたら finish が呼ばれるまで持ってからそのスレッドで放す。"""
        try:
            self.lock = self._acquire(self._name, self._timeout_sec)
        except Exception as error:  # noqa: BLE001 取れなかった理由を控え、検証はテスト本体が行うため
            self.error = error
        self._done.set()
        if self.lock is not None:
            self._finish.wait(JOIN_TIMEOUT_SEC)
            self.lock.release()

    def wait(self, timeout_sec: float) -> bool:
        """取れたか取れなかったかが決まるまで待つ。決まれば True、上限まで待って決まらなければ False。"""
        return self._done.wait(timeout_sec)

    def finish(self) -> None:
        """取れていたロックをそのスレッドで放させ、スレッドの終わりを待つ。"""
        self._finish.set()
        self._thread.join(JOIN_TIMEOUT_SEC)


class OtherProcessHolder:
    """排他を持つ前のプロセスを模す。ミューテックスを持ち、少し後に終了の依頼のイベントを作って、立つのを待つ。

    前のプロセスが、ミューテックスを作ってからイベントを作るまでの間を再現する。
    終了の依頼が立ったら received を立て、ミューテックスを放して終わる。
    """

    def __init__(self, name: str, event_delay_sec: float) -> None:
        self._name = name
        self._event_delay_sec = event_delay_sec
        self.mutex_ready = threading.Event()
        """ミューテックスを持ったら立つ。"""
        self.received = threading.Event()
        """終了の依頼を受けたら立つ（ミューテックスを放す前に立つ）。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """ミューテックスを持ち、遅れてイベントを作り、終了の依頼を待って放す。"""
        mutex = _kernel32.CreateMutexW(None, True, mutex_name(self._name))
        self.mutex_ready.set()
        # イベントを作るまでの間（この間は OpenEventW が失敗する）
        time.sleep(self._event_delay_sec)
        event = _kernel32.CreateEventW(None, False, False, quit_event_name(self._name))
        if _kernel32.WaitForSingleObject(event, OTHER_PROCESS_WAIT_MS) == WAIT_OBJECT_0:
            self.received.set()
        _kernel32.ReleaseMutex(mutex)
        close_handle(event)
        close_handle(mutex)

    def finish(self) -> None:
        """スレッドの終わりを待つ。"""
        self._thread.join(JOIN_TIMEOUT_SEC)
