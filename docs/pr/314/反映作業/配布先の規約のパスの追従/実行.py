"""配布先の rules.yaml・agent_context.yaml の規約などの .md のパスを、変換後の YAML のパスへ書き換える。"""

import difflib
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from common import TARGETS, repo_root, rewrite  # noqa: E402

# 前提確認
root, dry_run = repo_root(sys.argv)
print("前提確認: ok")

# 計画（--dry-run もここを通る）
plans = []
for name in TARGETS:
    path = root / name
    if not path.is_file():
        print(f"{name}: skipped")
        continue
    old = path.read_text(encoding="utf-8")
    new = rewrite(old)
    if new == old:
        print(f"{name}: skipped")
        continue
    sys.stdout.writelines(
        difflib.unified_diff(old.splitlines(True), new.splitlines(True), str(path), str(path))
    )
    plans.append((path, new))
    if dry_run:
        print(f"{name}: changed")
if dry_run:
    sys.exit(0)

# 適用（退避 → 置き換え）
for path, new in plans:
    shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.write_text(new, encoding="utf-8")
    print(f"{path.name}: changed")
