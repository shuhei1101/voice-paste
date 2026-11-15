"""配布先の .claude/settings.json に旧い環境変数が無く、索引が rule-inject の設定ファイルにあるかを確かめる。

引数: {対象のリポジトリの場所}
"""

import json
import subprocess
import sys
from pathlib import Path

ENV_KEY = "RULE_INJECT_INDEXES_PROJECT"
SETTINGS_JSON = Path(".claude/settings.json")
RULE_INJECT_SETTINGS = Path("~/.config/rule-inject/settings.yaml").expanduser()


def main() -> int:
    """旧い環境変数の有無と、projects の match の有無を出す。"""
    repo = Path(sys.argv[1]).resolve()
    common_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    clone = Path(common_dir).parent
    settings_json = repo / SETTINGS_JSON
    env = (
        json.loads(settings_json.read_text(encoding="utf-8")).get("env", {})
        if settings_json.exists()
        else {}
    )
    removed = ENV_KEY not in env
    print(f"{SETTINGS_JSON} の {ENV_KEY}: {'ok（無い）' if removed else 'failed（残っている）'}")
    text = RULE_INJECT_SETTINGS.read_text(encoding="utf-8") if RULE_INJECT_SETTINGS.exists() else ""
    matched = f"match: '{clone}'" in text or f"match: {clone}\n" in text
    print(
        f"rule-inject の設定ファイルの match: {'ok' if matched else 'skipped（移す値が無いか、直下の rules.yaml だけの配布先）'}"
    )
    return 0 if removed else 1


if __name__ == "__main__":
    sys.exit(main())
