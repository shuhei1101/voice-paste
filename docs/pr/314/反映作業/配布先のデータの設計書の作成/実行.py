"""配布先の ER 図の `source` を持たないテーブルごとにデータの設計書を作成し、テーブルとカラムの `source` で指す。"""

import difflib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    DATA_DIR,
    DATA_ROW,
    DEV_DOCS,
    ID_RE,
    INDEX_SUMMARY,
    build_data_doc,
    data_mid,
    dirty_paths,
    er_files,
    er_schema_ref,
    fail,
    field_key,
    ignored_rule,
    parse_args,
)

args = parse_args(sys.argv[1:])
if args is None:
    fail(
        "前提確認",
        "第 1 引数に配布先のリポジトリの直下を、第 2 引数に --dry-run だけを渡してください",
    )
root, dry_run = args
try:
    import yaml
    from ruamel.yaml import YAML
except ImportError as e:
    fail("前提確認", f"PyYAML と ruamel.yaml が要ります: {e}")
files = er_files(root)
if not files:
    print("前提確認: ok")
    print("データの設計書の作成: skipped")
    sys.exit(0)
dirty = dirty_paths(root, [p.relative_to(root) for p in files] + [DEV_DOCS, DATA_DIR])
if dirty:
    fail("前提確認", "書き換える対象に未 commit の変更があります:\n" + "\n".join(dirty))
dev_docs_path = root / DEV_DOCS
dev_docs = dev_docs_path.read_text(encoding="utf-8")
schema_ref = er_schema_ref(yaml.safe_load(dev_docs) or {})
if not schema_ref:
    fail("前提確認", "dev-docs.yaml に schema.ref を持つ er の行がありません")
print("前提確認: ok")

rt = YAML()
rt.preserve_quotes = True
rt.width = 4096
rt.indent(mapping=2, sequence=4, offset=2)
data_folder = root / DATA_DIR
existing = (
    [
        yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for p in sorted(data_folder.glob("*.yaml"))
        if p.name != "index.yaml"
    ]
    if data_folder.is_dir()
    else []
)
er_docs = [(p, p.read_text(encoding="utf-8")) for p in files]
mid = data_mid(existing, [yaml.safe_load(t) or {} for _, t in er_docs])
if mid is None:
    fail(
        "前提確認",
        "ER 図の ID から番号を決められません（`{種類}-{番号}-{連番}` か `{種類}-{番号}` の形の ID がありません）",
    )
next_n = 1 + max(
    [int(m.group("n")) for d in existing if (m := ID_RE.match(str(d.get("id", ""))))] or [0]
)

writes = {}
new_docs = []
for path, text in er_docs:
    doc = rt.load(text)
    changed = False
    for table in doc.get("tables") or []:
        if table.get("source"):
            continue
        doc_id = f"DATA-{mid}-{next_n}" if mid else f"DATA-{next_n}"
        next_n += 1
        keys = list(table.keys())
        table.insert(keys.index("title") + 1 if "title" in keys else 1, "source", f"{doc_id}#")
        for c in table.get("columns") or []:
            if "source" not in c:
                ck = list(c.keys())
                c.insert(
                    ck.index("title") + 1 if "title" in ck else 1,
                    "source",
                    f"{doc_id}#fields[{field_key(c['name'])}]",
                )
        new_docs.append(build_data_doc(doc_id, doc["id"], table))
        changed = True
    if changed:
        buf = io.StringIO()
        rt.dump(doc, buf)
        writes[path] = (text, buf.getvalue())

if not new_docs:
    print("データの設計書の作成: skipped")
    sys.exit(0)
rule = ignored_rule(root)
if rule:
    fail("docs/data/ の追跡", f"docs/data/ が .gitignore で除外されています: {rule}")
print("docs/data/ の追跡: ok")

index_path = data_folder / "index.yaml"
index = (
    yaml.safe_load(index_path.read_text(encoding="utf-8"))
    if index_path.is_file()
    else {"summary": INDEX_SUMMARY, "items": []}
)
for d in new_docs:
    body = yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=1000)
    writes[data_folder / f"{d['id']}.yaml"] = ("", body)
    index.setdefault("items", []).append(
        {"page": f"{d['id']}.yaml", "summary": d["title"].split(": ", 1)[1]}
    )
old_index = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
writes[index_path] = (
    old_index,
    yaml.safe_dump(index, allow_unicode=True, sort_keys=False, width=1000),
)
if not any(d.get("id") == "data" for d in (yaml.safe_load(dev_docs) or {}).get("documents") or []):
    marker = "documents:\n"
    if marker not in dev_docs:
        fail("dev-docs.yaml の data の行", "documents: の行がありません")
    writes[dev_docs_path] = (
        dev_docs,
        dev_docs.replace(marker, marker + DATA_ROW.format(ref=schema_ref), 1),
    )
    print("dev-docs.yaml の data の行: changed")
else:
    print("dev-docs.yaml の data の行: skipped")

for path, (old, new) in writes.items():
    rel = path.relative_to(root)
    sys.stdout.writelines(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="/dev/null" if not old else str(rel),
            tofile=str(rel),
        )
    )
for d in new_docs:
    print(f"{d['title']}（{d['id']}）: changed")
if dry_run:
    sys.exit(0)

# 適用（検証 → 書き込み）
for path, (_, new) in writes.items():
    try:
        yaml.safe_load(new)
    except yaml.YAMLError as e:
        fail("検証", f"{path}: {e}")
print("検証: ok")
data_folder.mkdir(parents=True, exist_ok=True)
for path, (_, new) in writes.items():
    path.write_text(new, encoding="utf-8")
print("データの設計書の作成: changed")
