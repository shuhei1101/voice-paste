"""settings.yaml と残す索引を読み取りだけで確かめ、モニターへ繋がるかを確かめる。"""

import socket
import sys
from pathlib import Path

import yaml

TARGET = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml")
KEPT_INDEX = Path("/mnt/c/Users/shuhe/repo/voice-paste/docs/rules.yaml")
MONITOR_PORT_FILE = Path("/mnt/c/Users/shuhe/repo/ai-monitor/data/monitor.port")
CONNECT_TIMEOUT_SEC = 5


def main() -> int:
    """対象ごとに読めるかを 1 行ずつ出す。"""
    failed = False
    # settings.yaml が YAML として読めるか
    try:
        yaml.safe_load(TARGET.read_text(encoding="utf-8"))
        print("settings.yaml: ok")
    except (OSError, yaml.YAMLError):
        print("settings.yaml: failed")
        failed = True
    # 残す索引が読めるか
    if KEPT_INDEX.is_file():
        print("voice-paste の docs/rules.yaml: ok")
    else:
        print("voice-paste の docs/rules.yaml: failed")
        failed = True
    # モニターのポートへ繋がるか（再読込は要求しない）
    try:
        port = int(MONITOR_PORT_FILE.read_text(encoding="utf-8").strip())
        with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT_SEC):
            pass
        print(f"モニター（127.0.0.1:{port}）: ok")
    except (OSError, ValueError):
        print("モニター: failed")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
