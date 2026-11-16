"""配布先の mdmark.config.yaml の map.kinds・map.lines に、AI Monitor が生成する図の種類を記載する。"""

from __future__ import annotations

import difflib
import os
import sys
import tempfile

from common import KINDS, LINES, TARGET, dump, fail, missing_kinds, repo_from_args, yaml_rt

repo, dry_run = repo_from_args(sys.argv, allow_dry_run=True)
path = repo / TARGET
rt = yaml_rt()
current = path.read_text(encoding="utf-8") if path.exists() else None
doc = rt.load(current) if current else None
if doc is None:
    doc = {}
if not isinstance(doc, dict):
    fail("前提確認", f"{TARGET} の最上位がオブジェクトではありません")
print("前提確認: ok")

# 計画（--dry-run もここを通る）
if not missing_kinds(doc):
    print("map.kinds の記載: skipped")
    sys.exit(0)
mapping = doc.setdefault("map", {})
kinds = mapping.setdefault("kinds", {})
lines = mapping.setdefault("lines", {})
for name, value in KINDS.items():
    kinds[name] = dict(value)
for name, value in LINES.items():
    lines[name] = dict(value)
new_text = dump(rt, doc)
sys.stdout.writelines(
    difflib.unified_diff(
        (current or "").splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(path) if current is not None else "/dev/null",
        tofile=str(path),
    )
)
if dry_run:
    print("map.kinds の記載: changed")
    sys.exit(0)

# 適用（一時ファイル → 検証 → 退避 → 置き換え）
fd, tmp = tempfile.mkstemp(dir=repo, suffix=".yaml")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(new_text)
if missing_kinds(yaml_rt().load(open(tmp, encoding="utf-8").read())):
    os.unlink(tmp)
    fail("検証")
print("検証: ok")
# 元のファイルがあれば退避し、無ければ作ったことを残す（切り戻しが使う）
if current is not None:
    (repo / f"{TARGET}.bak").write_text(current, encoding="utf-8")
else:
    (repo / f"{TARGET}.created").write_text("", encoding="utf-8")
os.replace(tmp, path)
print("map.kinds の記載: changed")
