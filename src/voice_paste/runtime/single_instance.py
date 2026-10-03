"""単一インスタンスの排他。名前付きのミューテックスで 1 つに絞り、後から起動したプロセスが前のプロセスへ終わるよう頼む。

Win32 の名前付きのミューテックス（`Local\\{名前}`）を持つプロセスが、常駐サービスの 1 つだけ。
後から起動したプロセスは、名前付きのイベント（`Local\\{名前}-quit`）を立てて前のプロセスに終わるよう頼み、
ミューテックスが放されるのを待ってから取る。プロセスの番号での強制終了はしない
（番号を使い回された無関係なプロセスを止めない）。
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from voice_paste.shared.constants import APP_NAME
from voice_paste.shared.errors import StartupError

logger = logging.getLogger(__name__)

INSTANCE_HASH_LENGTH: int = 16
"""instance_name が名前に使う SHA-256 の 16 進の文字数。置き場所が 1 台に数個のため、16 文字（64 ビット）で重ならない。"""

OPEN_EVENT_RETRY_INTERVAL_SEC: float = 0.1
"""前のプロセスがミューテックスを作ってからイベントを作るまでの間に OpenEventW が失敗したとき、開き直す間隔。前のプロセスの起動の初めの数ミリ秒の間だけ起こるため、依頼の遅れを 0.1 秒までに抑える。"""

ERROR_ALREADY_EXISTS: int = 183
"""CreateMutexW が、同じ名前のミューテックスが既にあるときに GetLastError で返す値。"""

EVENT_MODIFY_STATE: int = 0x0002
"""イベントを立てる権限。"""

WAIT_OBJECT_0: int = 0x00000000
"""待っていたものが立った（ミューテックスなら取れた）。WaitForMultipleObjects では立った先頭のものの番号になる。"""

WAIT_ABANDONED: int = 0x00000080
"""持ち主が放さずに終わったミューテックスを取れた。前のプロセスが片付けずに落ちた場合で、取れたものとして扱う。"""

WAIT_FAILED: int = 0xFFFFFFFF
"""待つ呼び出しそのものが失敗した。"""

INFINITE: int = 0xFFFFFFFF
"""待つ時間に上限を置かない。"""

MILLISECONDS_PER_SECOND: int = 1000
"""秒をミリ秒にする倍率。"""

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.restype = wintypes.BOOL
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForMultipleObjects.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.BOOL,
    wintypes.DWORD,
]
_kernel32.WaitForMultipleObjects.restype = wintypes.DWORD


def instance_name(settings_dir: Path) -> str:
    """設定の置き場所から、単一インスタンスの排他の名前（`voice-paste-{ハッシュ}`）を作る。"""
    # 解決した絶対パスを小文字にして、大文字・小文字の違いで別の名前にならないようにする
    normalized = str(settings_dir.resolve()).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{APP_NAME}-{digest[:INSTANCE_HASH_LENGTH]}"


def _mutex_name(name: str) -> str:
    """排他の名前から、名前付きのミューテックスの名前を作る。"""
    return f"Local\\{name}"


def _quit_event_name(name: str) -> str:
    """排他の名前から、終了の依頼の名前付きのイベントの名前を作る。"""
    return f"Local\\{name}-quit"


def _win_error(action: str) -> StartupError:
    """直前の Win32 の呼び出しの失敗を、何をしようとしたかを添えた StartupError にする。"""
    return StartupError(f"{action}ができない（{ctypes.WinError(ctypes.get_last_error())}）")


class SingleInstanceLock:
    """取った名前付きのミューテックスと、終了の依頼を待つスレッドを持つ。

    終了の依頼のイベント（名前付き）と停止のイベント（名前の無い自分専用）を専用のデーモンスレッドで待ち、
    終了の依頼が立ったら on_quit_requested で渡された関数を 1 回呼んでスレッドを終える
    （呼ぶのはそのスレッド。メインスレッドへ渡すのは渡す側の関数が行う）。
    名前付きのイベントは自分では立てない（立てると、ハンドルが残る間に次のプロセスへ依頼が引き継がれる）。
    ミューテックスは取ったスレッド（メインスレッド）で放す。
    """

    def __init__(self, mutex: int, quit_event: int) -> None:
        """取ったミューテックスと終了の依頼のイベントを受け、待つスレッドを始める。"""
        self._mutex = mutex
        self._quit_event = quit_event
        self._stop_event: int = _kernel32.CreateEventW(None, False, False, None)
        self._on_quit: Callable[[], None] | None = None
        self._quit_requested = False
        self._on_quit_called = False
        self._state_lock = threading.Lock()
        self._released = False
        self._thread = threading.Thread(target=self._wait_for_quit, name="single-instance", daemon=True)
        self._thread.start()

    def on_quit_requested(self, callback: Callable[[], None]) -> None:
        """終了を頼まれたときに呼ぶ関数を渡す。渡す前に頼まれていれば、その場で 1 回呼ぶ。"""
        with self._state_lock:
            self._on_quit = callback
            # 受け手を渡す前に頼まれていて、まだ呼んでいないか
            call_now = self._quit_requested and not self._on_quit_called
            self._on_quit_called = self._on_quit_called or call_now
        if call_now:
            callback()

    def release(self) -> None:
        """待つスレッドを止め、ミューテックスを放してハンドルを閉じる。2 回目以降は何もしない。"""
        if self._released:
            return
        self._released = True
        # 名前付きの終了の依頼のイベントは立てず、自分専用の停止のイベントでスレッドを抜けさせる
        _kernel32.SetEvent(self._stop_event)
        self._thread.join()
        _kernel32.ReleaseMutex(self._mutex)
        for handle in (self._mutex, self._quit_event, self._stop_event):
            _kernel32.CloseHandle(handle)

    def _wait_for_quit(self) -> None:
        """終了の依頼か停止のイベントが立つまで待ち、終了の依頼なら受け手を 1 回呼んで終わる。"""
        handles = (wintypes.HANDLE * 2)(self._quit_event, self._stop_event)
        signaled = _kernel32.WaitForMultipleObjects(2, handles, False, INFINITE)
        # 停止のイベントが立った（または待つ呼び出しが失敗した）か
        if signaled != WAIT_OBJECT_0:
            # はい: 受け手を呼ばずに終わる
            if signaled == WAIT_FAILED:
                logger.error(f"終了の依頼を待てない（{ctypes.WinError(ctypes.get_last_error())}）")
            return
        with self._state_lock:
            self._quit_requested = True
            callback = self._on_quit
            # 受け手がまだ無い、または呼んである（2 回目以降の依頼）か
            if callback is None or self._on_quit_called:
                # はい: ここでは呼ばない（受け手が渡されたときに呼ぶ）
                return
            self._on_quit_called = True
        callback()


def _ask_previous_to_quit(name: str) -> bool:
    """前のプロセスの終了の依頼のイベントを開いて立てる。開けなければ False。"""
    event = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, _quit_event_name(name))
    if not event:
        return False
    _kernel32.SetEvent(event)
    _kernel32.CloseHandle(event)
    return True


def _wait_for_release(mutex: int, name: str, timeout_sec: float) -> bool:
    """前のプロセスに終わるよう頼みながら、ミューテックスが放されるのを上限まで待つ。取れたら True。

    前のプロセスがミューテックスを作ってからイベントを作るまでの間はイベントを開けないため、
    開けるまで OPEN_EVENT_RETRY_INTERVAL_SEC ごとに開き直す（開けたらその時点で頼む）。
    """
    deadline = time.monotonic() + timeout_sec
    asked = False
    while (remaining_sec := deadline - time.monotonic()) > 0:
        # まだ頼めていなければ、イベントを開いて頼む
        if not asked:
            asked = _ask_previous_to_quit(name)
            if asked:
                logger.info("前の常駐サービスに終わるよう頼んだ")
        # 頼めた後は上限までまとめて待ち、頼めていない間は開き直す間隔で区切って待つ
        wait_sec = remaining_sec if asked else min(remaining_sec, OPEN_EVENT_RETRY_INTERVAL_SEC)
        wait_ms = max(1, int(wait_sec * MILLISECONDS_PER_SECOND))
        result = _kernel32.WaitForSingleObject(mutex, wait_ms)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            return True
        if result == WAIT_FAILED:
            raise _win_error("前の常駐サービスの終わりを待つこと")
    if not asked:
        logger.error("前の常駐サービスの終了の依頼のイベントを上限まで開けなかった")
    return False


def acquire_single_instance(name: str, timeout_sec: float) -> SingleInstanceLock:
    """名前付きのミューテックスを取る。取られていれば終了の依頼のイベントで前のプロセスに終わるよう頼み、放されるのを待ってから取る。"""
    # 1. 名前付きのミューテックスを作る（無ければ作った側が持つ）
    mutex = _kernel32.CreateMutexW(None, True, _mutex_name(name))
    if not mutex:
        raise _win_error("排他のミューテックスを作ること")
    already_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    # 2. 既にあった（前のプロセスが持っている）か
    if already_exists:
        # ある: 終わるよう頼み、放されるのを上限まで待つ
        try:
            released = _wait_for_release(mutex, name, timeout_sec)
        except StartupError:
            _kernel32.CloseHandle(mutex)
            raise
        if not released:
            _kernel32.CloseHandle(mutex)
            raise StartupError(f"前の常駐サービスが {timeout_sec} 秒たっても終わらない")

    # 3. 自分の終了の依頼のイベントを作り、立ったまま残っていた依頼を消す
    # （同じ名前のイベントは前のプロセスのハンドルが残る間は引き継がれ、取る前に立った依頼は前のプロセス宛てのため）
    quit_event = _kernel32.CreateEventW(None, False, False, _quit_event_name(name))
    if not quit_event:
        _kernel32.CloseHandle(mutex)
        raise _win_error("終了の依頼のイベントを作ること")
    _kernel32.ResetEvent(quit_event)

    # 4. 終了の依頼を待つスレッドを始める
    logger.info(f"単一インスタンスを確保した（{name}）")
    return SingleInstanceLock(mutex, quit_event)
