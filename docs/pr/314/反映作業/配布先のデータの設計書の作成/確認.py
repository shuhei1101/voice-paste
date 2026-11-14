"""配布先の ER 図の全てのテーブルが `source` を持ち、テーブルとカラムの `source` が指すデータの設計書とキーがあることを読むだけで確かめる。"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, er_files, fail, parse_args

REF = re.compile(r"^(?P<id>[A-Z]+-\d+(?:-\d+)?)#(?:fields\[(?P<key>.+)\])?$")
args = parse_args(sys.argv[1:])
if args is None:
    fail("前提確認", "第 1 引数に配布先のリポジトリの直下を渡してください")
root, _ = args
import yaml  # noqa: E402

data = {}
folder = root / DATA_DIR
if folder.is_dir():
    for p in folder.rglob("*.yaml"):
        if p.name != "index.yaml":
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            data[str(d.get("id"))] = {str(f.get("key")) for f in d.get("fields") or []}
missing, broken, tables = [], [], 0
for path in er_files(root):
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for t in doc.get("tables") or []:
        tables += 1
        if not t.get("source"):
            missing.append(f"{path.relative_to(root)}: tables[{t.get('name')}]")
        refs = [("tables", t.get("name"), t.get("source"))] + [
            ("columns", c.get("name"), c.get("source")) for c in t.get("columns") or []
        ]
        for kind, name, ref in refs:
            if not ref:
                continue
            m = REF.match(str(ref))
            if (
                not m
                or m.group("id") not in data
                or (m.group("key") and m.group("key") not in data[m.group("id")])
            ):
                broken.append(f"{path.relative_to(root)}: {kind}[{name}].source = {ref}")
print(f"ER 図のテーブル: {tables} 件")
if missing:
    fail("tables[].source の欠落", "\n".join(missing))
print("tables[].source の欠落: ok（0 件）")
if broken:
    fail("参照先の ID の設計書", "\n".join(broken))
print("参照先の ID の設計書: ok（0 件）")
