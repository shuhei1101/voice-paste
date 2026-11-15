"""配布先の dev-docs.yaml がコピーを指さず、コピーが無いことを読むだけで確かめる。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SCHEMA_LINE, COPIES, copies, fail, parse_args  # noqa: E402

args = parse_args(sys.argv[1:])
if args is None:
    fail("前提確認", "第 1 引数に配布先のリポジトリの直下を渡してください")
root, _ = args
remaining = [
    line.strip()
    for line in (root / "dev-docs.yaml").read_text(encoding="utf-8").splitlines()
    if (m := SCHEMA_LINE.match(line)) and COPIES.get(m.group("name"))
]
if remaining:
    fail("dev-docs.yaml の参照", "\n".join(remaining))
print("dev-docs.yaml の参照: ok")
left = copies(root)
if left:
    fail("コピー", "\n".join(str(p) for p in left))
print("コピー: ok")
