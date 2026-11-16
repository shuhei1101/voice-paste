"""配布先の mdmark.config.yaml の map.kinds・map.lines に、AI Monitor が生成する図の種類があるかを読むだけで確かめる。"""

from __future__ import annotations

import sys

from common import TARGET, fail, missing_kinds, repo_from_args, yaml_rt

repo, _ = repo_from_args(sys.argv, allow_dry_run=False)
path = repo / TARGET
if not path.exists():
    fail("map.kinds の値", f"{TARGET} がありません")
missing = missing_kinds(yaml_rt().load(path.read_text(encoding="utf-8")))
if missing:
    fail("map.kinds の値", f"足りない・違う種類: {', '.join(missing)}")
print("map.kinds の値: ok")
