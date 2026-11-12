"""Windows: 抑止の間にスクリーンセーバーが動かないかの PoC。

W2・W1・対照（抑止なし）の順に、無操作が 90 秒続いた時点の SPI_GETSCREENSAVERRUNNING を読む。
スクリーンセーバーの設定は終わったら元に戻す。
使い方: python windows_screensaver.py
"""

import ctypes
import subprocess
import threading
import time
import winreg
from ctypes import wintypes

from windows_inhibit import W1, W2, display_required

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")
kernel32.GetTickCount.restype = wintypes.DWORD

SPI_GETSCREENSAVEACTIVE = 0x0010
SPI_SETSCREENSAVEACTIVE = 0x0011
SPI_GETSCREENSAVETIMEOUT = 0x000E
SPI_SETSCREENSAVETIMEOUT = 0x000F
SPI_GETSCREENSAVERRUNNING = 0x0072
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
DESKTOP_KEY = r"Control Panel\Desktop"
BLANK_SAVER = r"C:\Windows\System32\scrnsave.scr"
IDLE_SECONDS = 90
MAX_WAIT_SECONDS = 15 * 60


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(info))
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def spi_get(action: int) -> int:
    value = wintypes.UINT()
    user32.SystemParametersInfoW(action, 0, ctypes.byref(value), 0)
    return value.value


def spi_set(action: int, value: int) -> None:
    user32.SystemParametersInfoW(action, value, None, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)


SAVER_VALUES = ("ScreenSaveActive", "ScreenSaveTimeOut", "SCRNSAVE.EXE")


def read_saver_values() -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY) as key:
        for name in SAVER_VALUES:
            try:
                values[name] = winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                values[name] = None
    return values


def write_saver_values(values: dict[str, str | None]) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def reset_idle() -> None:
    """マウスの入力を 1 px 分送って戻し、無操作の時間を 0 から数え直す。"""
    mouseeventf_move = 0x0001
    user32.mouse_event(mouseeventf_move, 1, 0, 0, 0)
    user32.mouse_event(mouseeventf_move, -1, 0, 0, 0)


def close_saver() -> None:
    """測定で動いたスクリーンセーバーのプロセスを終了する（別のデスクトップで動くため入力では閉じない）。"""
    subprocess.run(["taskkill", "/F", "/IM", "scrnsave.scr"], capture_output=True)
    time.sleep(2)
    print(f"  閉じた後: saver_running={bool(spi_get(SPI_GETSCREENSAVERRUNNING))}", flush=True)


def wait_idle_and_read(label: str) -> dict[str, object]:
    start = time.monotonic()
    while time.monotonic() - start < MAX_WAIT_SECONDS:
        if idle_seconds() >= IDLE_SECONDS:
            result = {
                "label": label,
                "idle_s": round(idle_seconds(), 1),
                "saver_running": bool(spi_get(SPI_GETSCREENSAVERRUNNING)),
                "display_required": display_required(),
            }
            print(result, flush=True)
            return result
        time.sleep(1)
    result = {"label": label, "idle_s": round(idle_seconds(), 1), "saver_running": None, "timeout": True}
    print(result, flush=True)
    return result


def run_with(label: str, impl: W1 | W2 | None) -> None:
    reset_idle()
    if impl is not None:
        t = threading.Thread(target=impl.inhibit)
        t.start()
        t.join()  # 抑止を依頼したスレッドは終わる
    try:
        wait_idle_and_read(label)
    finally:
        if impl is not None:
            impl.release()
        close_saver()


def main() -> None:
    saved = read_saver_values()
    saved_spi = (spi_get(SPI_GETSCREENSAVEACTIVE), spi_get(SPI_GETSCREENSAVETIMEOUT))
    print(f"元の設定: {saved} spi={saved_spi}", flush=True)
    try:
        write_saver_values({"SCRNSAVE.EXE": BLANK_SAVER})
        spi_set(SPI_SETSCREENSAVETIMEOUT, 60)
        spi_set(SPI_SETSCREENSAVEACTIVE, 1)
        run_with("w2", W2())
        run_with("w1", W1())
        run_with("control", None)
    finally:
        close_saver()
        user32.SystemParametersInfoW(SPI_SETSCREENSAVEACTIVE, saved_spi[0], None, 0)
        user32.SystemParametersInfoW(SPI_SETSCREENSAVETIMEOUT, saved_spi[1], None, 0)
        write_saver_values(saved)
        print(f"戻した設定: {read_saver_values()}", flush=True)


if __name__ == "__main__":
    main()
