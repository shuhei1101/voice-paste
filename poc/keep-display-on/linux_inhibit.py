"""Linux: gnome-session-inhibit ... cat を標準入力のパイプで生かす抑止の PoC。

使い方: python3 linux_inhibit.py {hold|close|child-kill|parent-kill}
"""

import os
import signal
import subprocess
import sys
import threading
import time


def start_inhibit() -> subprocess.Popen[bytes]:
    """抑止の子プロセスを、呼んだスレッドを終えても残る形で起こす。"""
    holder: dict[str, subprocess.Popen[bytes]] = {}

    def spawn() -> None:
        holder["proc"] = subprocess.Popen(
            [
                "gnome-session-inhibit",
                "--inhibit", "idle",
                "--app-id", "voice-paste",
                "--reason", "recording",
                "cat",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )

    t = threading.Thread(target=spawn)
    t.start()
    t.join()  # 呼び出し元のスレッドは終わる
    return holder["proc"]


def listing() -> str:
    return subprocess.run(
        ["gnome-session-inhibit", "--list"], capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    mode = sys.argv[1]
    proc = start_inhibit()
    time.sleep(1)
    print(f"[{mode}] 抑止中: {listing()!r}", flush=True)
    if mode == "close":
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=5)
    elif mode == "child-kill":
        proc.kill()
        proc.wait(timeout=5)
    elif mode == "parent-kill":
        print(f"child_pid={proc.pid}", flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
    time.sleep(1)
    print(f"[{mode}] 解除後: {listing()!r}", flush=True)


if __name__ == "__main__":
    main()
