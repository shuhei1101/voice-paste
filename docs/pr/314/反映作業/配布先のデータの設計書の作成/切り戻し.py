"""実行.py が書き換えた配布先の ER 図・dev-docs.yaml・docs/data/ を、commit する前の状態へ戻す。"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, DEV_DOCS, ER_DIR, fail, parse_args

args = parse_args(sys.argv[1:])
if args is None or args[1]:
    fail("前提確認", "第 1 引数に配布先のリポジトリの直下だけを渡してください")
root, _ = args
print("前提確認: ok")
targets = [str(ER_DIR), str(DEV_DOCS), str(DATA_DIR)]
for target in targets:
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", target], capture_output=True, text=True
    ).stdout.strip()
    if not tracked:
        print(f"{target} の書き戻し: skipped")
        continue
    r = subprocess.run(
        ["git", "-C", str(root), "restore", "--staged", "--worktree", "--", target],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        fail(f"{target} の書き戻し", r.stderr)
    print(f"{target} の書き戻し: changed")
r = subprocess.run(
    ["git", "-C", str(root), "clean", "-f", "--", str(DATA_DIR)],
    capture_output=True,
    text=True,
)
if r.returncode != 0:
    fail("作成したデータの設計書の削除", r.stderr)
print("作成したデータの設計書の削除: " + ("changed" if r.stdout.strip() else "skipped"))
