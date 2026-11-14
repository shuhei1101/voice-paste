"""配布先のリポジトリの docs/rules.yaml を直下の rules.yaml へ移し、rule の相対パスを移した先から辿れる形に直す。"""
from __future__ import annotations

import difflib
import posixpath
import re
import subprocess
import sys
from pathlib import Path

import yaml

# `rule:` の値のうち、相対パスで書かれたものだけを直す（URL・絶対パス・変数参照はそのまま）
RULE_LINE = re.compile(r"^(\s*-?\s*rule:\s*)(\S.*?)\s*$")


def relocate(value: str) -> str:
    """docs/ からの相対パスを、リポジトリの直下からの相対パスに直す。"""
    if value.startswith(("/", "http://", "https://", "!{", '"', "'")):
        return value
    return posixpath.normpath(posixpath.join("docs", value))


def plan(text: str) -> str:
    """rule の値を直した本文を返す。"""
    out = []
    for line in text.splitlines(keepends=True):
        match = RULE_LINE.match(line)
        if match:
            line = f"{match.group(1)}{relocate(match.group(2))}\n"
        out.append(line)
    return "".join(out)


def main() -> int:
    """前提確認 → 計画 → 適用の順に索引を移す。"""
    args = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[2:]
    # 前提確認
    if not args or not (Path(args[0]) / ".git").exists():
        print("前提確認: failed")
        return 1
    repo = Path(args[0])
    old, new = repo / "docs" / "rules.yaml", repo / "rules.yaml"
    if not old.is_file():
        print("前提確認: ok")
        print("索引の移動: skipped")
        return 0
    if new.exists():
        # 両方あると、どちらを残すか決まらない
        print("前提確認: failed")
        return 1
    print("前提確認: ok")
    # 計画（--dry-run もここを通る）
    before = old.read_text(encoding="utf-8")
    after = plan(before)
    sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after.splitlines(True), str(old), str(new)))
    if dry_run:
        print("索引の移動: changed")
        return 0
    # 適用（検証 → 移動 → 書き換え）
    try:
        yaml.safe_load(after)
    except yaml.YAMLError:
        print("検証: failed")
        return 1
    print("検証: ok")
    result = subprocess.run(["git", "-C", str(repo), "mv", "docs/rules.yaml", "rules.yaml"], capture_output=True, text=True)
    if result.returncode != 0:
        print("索引の移動: failed")
        return 1
    new.write_text(after, encoding="utf-8")
    print("索引の移動: changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
