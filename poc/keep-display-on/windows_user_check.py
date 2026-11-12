"""ユーザーに依頼する観点（昇格した powercfg /requests の突き合わせと、消灯の目視）の補助。

W2 で 3 分抑止し、その間だけ画面の消灯を 1 分にする。終わったら消灯の設定を元に戻す。
使い方: python windows_user_check.py
"""

import re
import subprocess
import threading
import time

from windows_inhibit import W2, display_required

HOLD_SECONDS = 180
VIDEO = ["SCHEME_CURRENT", "SUB_VIDEO", "VIDEOIDLE"]


def read_video_idle() -> tuple[int, int]:
    """今の電源プランの消灯までの秒数（AC, DC）。"""
    out = subprocess.run(["powercfg", "/query", *VIDEO], capture_output=True, text=True, errors="replace").stdout
    ac, dc = re.findall(r"0x[0-9a-fA-F]{8}", out)[-2:]
    return int(ac, 16), int(dc, 16)


def write_video_idle(ac: int, dc: int) -> None:
    subprocess.run(["powercfg", "/setacvalueindex", *VIDEO, str(ac)], check=True)
    subprocess.run(["powercfg", "/setdcvalueindex", *VIDEO, str(dc)], check=True)
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"], check=True)


def main() -> None:
    saved = read_video_idle()
    print(f"元の消灯までの秒数: AC={saved[0]} DC={saved[1]}")
    impl = W2()
    try:
        write_video_idle(60, 60)
        t = threading.Thread(target=impl.inhibit)
        t.start()
        t.join()
        print(f"抑止を始めました（DISPLAY={display_required()}）。消灯は 1 分にしています。")
        print("1. 30 秒以内に、管理者として開いた PowerShell で powercfg /requests を実行し、DISPLAY の欄を控えてください")
        print("2. その後はキーボードとマウスに触れず、2 分たっても画面が消えないかを見てください")
        time.sleep(HOLD_SECONDS)
    finally:
        impl.release()
        write_video_idle(*saved)
        print(f"抑止を解除しました（DISPLAY={display_required()}）。消灯の設定を戻しました: {read_video_idle()}")
        print("3. もう一度 powercfg /requests を実行し、DISPLAY の欄から python.exe が消えたかを控えてください")


if __name__ == "__main__":
    main()
