"""settings.yaml の my_plugins_repo と voice-input の rule_indexes が、あるべき値かを読むだけで確かめる。"""

import sys
from pathlib import Path

import yaml

TARGET = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml")
PROJECT_NAME = "voice-input"
MY_PLUGINS_REPO = "shuhei1101/my-plugins"
KEPT_INDEX = "/mnt/c/Users/shuhe/repo/voice-paste/docs/rules.yaml"


def main() -> int:
    """観測した値を出し、全てあるべき値なら 0 で終える。"""
    data = yaml.safe_load(TARGET.read_text(encoding="utf-8"))
    project = next(p for p in data["projects"] if p.get("name") == PROJECT_NAME)
    failed = False
    value = data.get("my_plugins_repo")
    # my_plugins_repo があるべき値か
    if value == MY_PLUGINS_REPO:
        print(f"my_plugins_repo の値: ok（{value}）")
    else:
        print(f"my_plugins_repo の値: failed（{value}）")
        failed = True
    indexes = project.get("rule_indexes")
    # rule_indexes が実在する索引だけか
    if indexes == [KEPT_INDEX]:
        print(f"rule_indexes の値: ok（{indexes}）")
    else:
        print(f"rule_indexes の値: failed（{indexes}）")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
