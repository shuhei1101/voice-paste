"""settings.yaml と残す索引を読み取りだけで確かめる。"""

import sys
from pathlib import Path

import yaml

TARGET = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml")
KEPT_INDEX = Path("/mnt/c/Users/shuhe/repo/voice-paste/docs/rules.yaml")


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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
