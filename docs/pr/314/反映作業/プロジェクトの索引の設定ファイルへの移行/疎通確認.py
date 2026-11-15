"""配布先のリポジトリの .claude/settings.json と rule-inject の設定ファイルを読み取りで確かめる。

引数: {対象のリポジトリの場所}
"""

import json
import sys
from pathlib import Path

SETTINGS_JSON = Path(".claude/settings.json")
RULE_INJECT_SETTINGS = Path("~/.config/rule-inject/settings.yaml").expanduser()


def main() -> int:
    """対象ごとに読めるかを出す。"""
    args = sys.argv[1:]
    if not args or not (Path(args[0]) / ".git").exists():
        print("対象のリポジトリ: failed（リポジトリの場所を第 1 引数で渡す）")
        return 1
    print("対象のリポジトリ: ok")
    settings_json = Path(args[0]) / SETTINGS_JSON
    if settings_json.exists():
        json.loads(settings_json.read_text(encoding="utf-8"))
        print(f"{SETTINGS_JSON}: ok")
    else:
        print(f"{SETTINGS_JSON}: ok（無い）")
    if RULE_INJECT_SETTINGS.is_file():
        print(f"{RULE_INJECT_SETTINGS}: ok")
    else:
        print(f"{RULE_INJECT_SETTINGS}: ok（無い。実行で作る）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
