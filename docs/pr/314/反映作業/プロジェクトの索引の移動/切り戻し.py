"""配布先のリポジトリの直下の rules.yaml を docs/rules.yaml へ戻し、rule の相対パスを docs/ からの形に戻す。"""
from __future__ import annotations

import posixpath
import re
import subprocess
import sys
from pathlib import Path

RULE_LINE = re.compile(r"^(\s*-?\s*rule:\s*)(\S.*?)\s*$")


def restore(value: str) -> str:
    """リポジトリの直下からの相対パスを、docs/ からの相対パスに戻す。"""
    if value.startswith(("/", "http://", "https://", "!{", '"', "'")):
        return value
    return posixpath.relpath(posixpath.normpath(value), "docs")


def main() -> int:
    """索引を docs/ へ戻す。"""
    if len(sys.argv) < 2 or not (Path(sys.argv[1]) / "rules.yaml").is_file():
        print("移した索引: failed")
        return 1
    repo = Path(sys.argv[1])
    text = (repo / "rules.yaml").read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines(keepends=True):
        match = RULE_LINE.match(line)
        lines.append(f"{match.group(1)}{restore(match.group(2))}\n" if match else line)
    result = subprocess.run(["git", "-C", str(repo), "mv", "rules.yaml", "docs/rules.yaml"], capture_output=True, text=True)
    if result.returncode != 0:
        print("索引の書き戻し: failed")
        return 1
    (repo / "docs" / "rules.yaml").write_text("".join(lines), encoding="utf-8")
    print("索引の書き戻し: changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
