"""実行が退避した rule-inject の設定ファイルと、.claude/settings.json の commit を戻す。

引数: {対象のリポジトリの場所}
"""

import shutil
import subprocess
import sys
from pathlib import Path

RULE_INJECT_SETTINGS = Path("~/.config/rule-inject/settings.yaml").expanduser()
BACKUP = RULE_INJECT_SETTINGS.with_name(RULE_INJECT_SETTINGS.name + ".bak-ai-monitor-3211")
SETTINGS_JSON = ".claude/settings.json"
SUBJECT = "RULE_INJECT_INDEXES_PROJECT を rule-inject の設定ファイルの projects へ移す（shuhei1101/ai-monitor#3040）"


def main() -> int:
    """設定ファイルをバックアップへ戻し、移した commit を打ち消す。"""
    repo = Path(sys.argv[1]).resolve()
    if BACKUP.is_file():
        shutil.copy2(BACKUP, RULE_INJECT_SETTINGS)
        print("rule-inject の設定ファイルの書き戻し: changed")
    else:
        print("rule-inject の設定ファイルの書き戻し: skipped（退避が無い）")
    log = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--format=%H",
            "--fixed-strings",
            f"--grep={SUBJECT}",
            "-1",
            "--",
            SETTINGS_JSON,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not log:
        print(f"{SETTINGS_JSON} の書き戻し: skipped")
        return 0
    subprocess.run(
        ["git", "-C", str(repo), "revert", "--no-edit", log], check=True, capture_output=True
    )
    print(f"{SETTINGS_JSON} の書き戻し: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
