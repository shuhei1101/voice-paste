"""Windows の電源要求の API（kernel32 の PowerCreateRequest・PowerSetRequest・PowerClearRequest）で、録音の間の画面の消灯とアイドルによるスリープを抑止する。ctypes の Win32 に触れるのはこのファイルだけ。"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any

from voice_paste.shared.errors import DisplayInhibitError

POWER_REQUEST_REASON: str = "voice-paste: recording"
"""PowerCreateRequest に渡す理由の文字列。`powercfg /requests` の表示に出る。"""

_POWER_REQUEST_CONTEXT_VERSION = 0
_POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1
_POWER_REQUEST_DISPLAY_REQUIRED = 0
_POWER_REQUEST_SYSTEM_REQUIRED = 1
# 抑止に設定する要求の種類（設定する順。解くときも同じ順）
_REQUEST_KINDS: tuple[int, ...] = (_POWER_REQUEST_DISPLAY_REQUIRED, _POWER_REQUEST_SYSTEM_REQUIRED)
# PowerCreateRequest が失敗したときに返す値
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ReasonContext(ctypes.Structure):
    """REASON_CONTEXT（理由を単純な文字列で持つ形）。"""

    _fields_ = (
        ("Version", wintypes.ULONG),
        ("Flags", wintypes.DWORD),
        ("SimpleReasonString", wintypes.LPWSTR),
    )


# 電源要求のハンドルを守るロック
_lock = threading.Lock()
# 持っている電源要求のハンドル。抑止していなければ None（inhibit_display と release_display だけが触る）
_handle: int | None = None
# 型を設定した kernel32（_kernel32 が初回に作る）
_kernel32_dll: Any = None


def inhibit_display() -> None:
    """電源要求を作り、画面の消灯とアイドルによるスリープを抑止する。抑止中なら何もしない。"""
    global _handle
    with _lock:
        # 1. 抑止は 1 つだけ持つ
        if _handle is not None:
            return
        kernel32 = _kernel32()

        # 2. 電源要求を作る
        reason = _ReasonContext(
            _POWER_REQUEST_CONTEXT_VERSION, _POWER_REQUEST_CONTEXT_SIMPLE_STRING, POWER_REQUEST_REASON
        )
        handle = kernel32.PowerCreateRequest(ctypes.byref(reason))
        if handle is None or handle == _INVALID_HANDLE_VALUE:
            raise DisplayInhibitError(f"電源要求を作れなかった（{ctypes.get_last_error()}）")

        # 3. 要求の種類を順に設定する。失敗したら設定した分を解いてハンドルを閉じる
        applied: list[int] = []
        for kind in _REQUEST_KINDS:
            if not kernel32.PowerSetRequest(handle, kind):
                error = ctypes.get_last_error()
                for applied_kind in applied:
                    kernel32.PowerClearRequest(handle, applied_kind)
                kernel32.CloseHandle(handle)
                raise DisplayInhibitError(f"電源要求を設定できなかった（種類 {kind}・{error}）")
            applied.append(kind)

        # 4. ハンドルを持つ
        _handle = handle


def release_display() -> None:
    """持っている電源要求を解いて閉じる。抑止していなければ何もしない。"""
    global _handle
    with _lock:
        if _handle is None:
            return
        # ハンドルを手放してから解く（解けなくても、次の抑止は新しい電源要求を作る）
        handle = _handle
        _handle = None
        kernel32 = _kernel32()
        failures: list[str] = []
        for kind in _REQUEST_KINDS:
            if not kernel32.PowerClearRequest(handle, kind):
                failures.append(f"PowerClearRequest（種類 {kind}・{ctypes.get_last_error()}）")
        if not kernel32.CloseHandle(handle):
            failures.append(f"CloseHandle（{ctypes.get_last_error()}）")
        if failures:
            raise DisplayInhibitError(f"電源要求を解けなかった（{'・'.join(failures)}）")


def _kernel32() -> Any:
    """電源要求の関数の型を設定した kernel32 を返す（初回だけ作る）。"""
    global _kernel32_dll
    if _kernel32_dll is None:
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.PowerCreateRequest.argtypes = (ctypes.POINTER(_ReasonContext),)
        dll.PowerCreateRequest.restype = wintypes.HANDLE
        dll.PowerSetRequest.argtypes = (wintypes.HANDLE, ctypes.c_int)
        dll.PowerSetRequest.restype = wintypes.BOOL
        dll.PowerClearRequest.argtypes = (wintypes.HANDLE, ctypes.c_int)
        dll.PowerClearRequest.restype = wintypes.BOOL
        dll.CloseHandle.argtypes = (wintypes.HANDLE,)
        dll.CloseHandle.restype = wintypes.BOOL
        _kernel32_dll = dll
    return _kernel32_dll
