"""open の Issue #258 のタイトルと本文の旧命名「セッションの上限」を「録音セッションの上限」に置き換える。"""

import json
import subprocess
import sys
from pathlib import Path

REPO = "shuhei1101/voice-paste"
ISSUE = "258"
OLD = "セッションの上限"
NEW = "録音セッションの上限"
BACKUP = Path.home() / ".local/state/voice-paste/pr-279/issue-258.json"


def _gh(*args: str) -> str:
    """gh を呼び、標準出力を返す。失敗したら例外を送出する。"""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _replace(text: str) -> str:
    """旧命名を新命名に置き換える。既に新命名になっている箇所は二重に置き換えない。"""
    return text.replace(NEW, "\x00").replace(OLD, NEW).replace("\x00", NEW)


def main() -> int:
    # 1. 前提確認: 引数は無しか --dry-run だけで、Issue を読める
    args = sys.argv[1:]
    if args not in ([], ["--dry-run"]):
        print("前提確認: failed")
        return 1
    dry_run = args == ["--dry-run"]
    current = json.loads(_gh("issue", "view", ISSUE, "--repo", REPO, "--json", "title,body,state"))
    if current["state"] != "OPEN":
        print("前提確認: failed")
        return 1
    print("前提確認: ok")

    # 2. 計画: 置き換えた後のタイトルと本文を作り、変わる行を出す（--dry-run もここを通る）
    title = _replace(current["title"])
    body = _replace(current["body"])
    if title == current["title"] and body == current["body"]:
        print("Issue の書き換え: skipped")
        return 0
    for name, before, after in (("title", current["title"], title), ("body", current["body"], body)):
        for old_line, new_line in zip(before.splitlines(), after.splitlines(), strict=True):
            if old_line != new_line:
                print(f"--- #{ISSUE} {name}\n-{old_line}\n+{new_line}")
    if dry_run:
        print("Issue の書き換え: changed")
        return 0

    # 3. 適用: 元のタイトルと本文を退避してから書き換える
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps({"title": current["title"], "body": current["body"]}, ensure_ascii=False), encoding="utf-8")
    print("退避: ok")
    _gh("issue", "edit", ISSUE, "--repo", REPO, "--title", title, "--body", body)
    print("Issue の書き換え: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
