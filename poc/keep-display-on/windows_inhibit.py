"""Windows: W1（SetThreadExecutionState の常駐スレッド）と W2（PowerSetRequest）の抑止の PoC。

使い方: python windows_inhibit.py {baseline|w1|w2} [hold_seconds]
"""

import ctypes
import queue
import sys
import threading
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
SYSTEM_EXECUTION_STATE = 16
POWER_REQUEST_CONTEXT_VERSION = 0
POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1
POWER_REQUEST_DISPLAY_REQUIRED = 0
POWER_REQUEST_SYSTEM_REQUIRED = 1


class REASON_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("Flags", wintypes.DWORD),
        ("SimpleReasonString", wintypes.LPWSTR),
    ]


kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
kernel32.SetThreadExecutionState.restype = wintypes.DWORD
kernel32.PowerCreateRequest.argtypes = [ctypes.POINTER(REASON_CONTEXT)]
kernel32.PowerCreateRequest.restype = wintypes.HANDLE
kernel32.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
kernel32.PowerSetRequest.restype = wintypes.BOOL
kernel32.PowerClearRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
kernel32.PowerClearRequest.restype = wintypes.BOOL


def system_execution_state() -> int:
    """非昇格で読めるシステム全体の実行状態。"""
    value = wintypes.ULONG()
    status = powrprof.CallNtPowerInformation(
        SYSTEM_EXECUTION_STATE, None, 0, ctypes.byref(value), ctypes.sizeof(value)
    )
    if status != 0:
        raise OSError(f"CallNtPowerInformation status=0x{status:08x}")
    return value.value


def display_required() -> bool:
    return bool(system_execution_state() & ES_DISPLAY_REQUIRED)


class W1:
    """SetThreadExecutionState を抑止用の常駐スレッドで呼ぶ。"""

    def __init__(self) -> None:
        self._q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            cmd = self._q.get()
            flags = ES_CONTINUOUS
            if cmd == "on":
                flags |= ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
            kernel32.SetThreadExecutionState(flags)

    def inhibit(self) -> None:
        self._q.put("on")

    def release(self) -> None:
        self._q.put("off")


class W2:
    """PowerCreateRequest / PowerSetRequest をハンドルで持つ。"""

    def __init__(self) -> None:
        self._reason = REASON_CONTEXT(
            POWER_REQUEST_CONTEXT_VERSION,
            POWER_REQUEST_CONTEXT_SIMPLE_STRING,
            "voice-paste: recording",
        )
        self._handle: int | None = None

    def inhibit(self) -> None:
        handle = kernel32.PowerCreateRequest(ctypes.byref(self._reason))
        if not handle or handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        for kind in (POWER_REQUEST_DISPLAY_REQUIRED, POWER_REQUEST_SYSTEM_REQUIRED):
            if not kernel32.PowerSetRequest(handle, kind):
                raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        for kind in (POWER_REQUEST_DISPLAY_REQUIRED, POWER_REQUEST_SYSTEM_REQUIRED):
            kernel32.PowerClearRequest(self._handle, kind)
        kernel32.CloseHandle(self._handle)
        self._handle = None


def main() -> None:
    mode = sys.argv[1]
    hold = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    print(f"[{mode}] 前: DISPLAY={display_required()} state=0x{system_execution_state():08x}", flush=True)
    if mode == "baseline":
        return
    impl = W1() if mode == "w1" else W2()
    t = threading.Thread(target=impl.inhibit)
    t.start()
    t.join()  # 抑止を依頼したスレッドは終わる
    time.sleep(hold)
    print(f"[{mode}] 抑止中（依頼したスレッドの終了後 {hold}s）: DISPLAY={display_required()}", flush=True)
    if len(sys.argv) > 3 and sys.argv[3] == "no-release":
        print(f"[{mode}] 解除せず待機（強制終了用）", flush=True)
        time.sleep(3600)
    t = threading.Thread(target=impl.release)
    t.start()
    t.join()
    time.sleep(0.5)
    print(f"[{mode}] 解除後: DISPLAY={display_required()}", flush=True)


if __name__ == "__main__":
    main()
