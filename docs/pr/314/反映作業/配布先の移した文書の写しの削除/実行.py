"""配布先のリポジトリから、移した文書の写しと、それを指す索引のエントリを消す。"""

from __future__ import annotations

import difflib
import os
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copies

# 1 つの配布先で消す写しの想定の上限（移した文書の数）
MAX_COPIES = len(copies.targets())


def main() -> int:
    """前提確認 → 計画 → 適用の順に写しを消す。"""
    args = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[2:]
    # 前提確認
    if not args or not (Path(args[0]) / ".git").exists():
        print("前提確認: failed")
        return 1
    repo = Path(args[0])
    found = copies.find_copies(repo)
    # 退避先を作れるか（git のディレクトリがディレクトリとして書けるか）
    git_dir = copies.backup_dir(repo).parent
    if len(found) > MAX_COPIES or not git_dir.is_dir() or not os.access(git_dir, os.W_OK):
        print("前提確認: failed")
        return 1
    print("前提確認: ok")
    print(f"退避先: {copies.backup_dir(repo)}")
    # 計画（--dry-run もここを通る）
    removed = set(found)
    indexes = {
        index: (
            (repo / index).read_text(encoding="utf-8"),
            copies.plan_index(index, (repo / index).read_text(encoding="utf-8"), removed),
        )
        for index in copies.INDEXES
        if (repo / index).is_file()
    }
    changed_indexes = [index for index, (before, after) in indexes.items() if before != after]
    if not found and not changed_indexes:
        print("写しの削除: skipped")
        return 0
    for path in found:
        print(f"消すファイル: {repo / path}")
    for index in changed_indexes:
        before, after = indexes[index]
        sys.stdout.writelines(
            difflib.unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                str(repo / index),
                str(repo / index),
            )
        )
    if dry_run:
        print("写しの削除: changed")
        return 0
    # 適用（検証 → 退避 → 削除・書き換え）
    for index in changed_indexes:
        try:
            yaml.safe_load(indexes[index][1])
        except yaml.YAMLError:
            print(f"{index} の検証: failed")
            return 1
    print("検証: ok")
    backup = copies.backup_dir(repo)
    for path in [*found, *changed_indexes]:
        (backup / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / path, backup / path)
    for path in found:
        (repo / path).unlink()
    for index in changed_indexes:
        (repo / index).write_text(indexes[index][1], encoding="utf-8")
    print("写しの削除: changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
