"""SystemExecutionState の ES_DISPLAY_REQUIRED を 1 回読む。"""
import ctypes
from ctypes import wintypes
v = wintypes.ULONG()
ctypes.WinDLL("powrprof").CallNtPowerInformation(16, None, 0, ctypes.byref(v), ctypes.sizeof(v))
print(f"DISPLAY={bool(v.value & 2)} state=0x{v.value:08x}")
