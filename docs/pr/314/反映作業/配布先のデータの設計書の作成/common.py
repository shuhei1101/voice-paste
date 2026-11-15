"""配布先のデータの設計書の作成の共通の定義。"""

import re
import subprocess
import sys
from pathlib import Path

ER_DIR = Path("docs/er")
DATA_DIR = Path("docs/data")
DEV_DOCS = Path("dev-docs.yaml")
DATA_ROW = """  - id: data
    title: データ
    paths: ["docs/data/**/*.yaml"]
    exclude: [index.yaml]
    schema:
      source: knowledge
      path: schemas/design/data.schema.yaml
      ref: {ref}
    writable: true
    metadata:
      name: title
      description: lead
      visibility: visibility
"""
INDEX_SUMMARY = "ER 図のテーブルが保存するデータの構造を、オブジェクトのキーの表で記載する設計書。"
MAX_ARGS = 2
CODE_QUOTES = 2
ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)-(?:(?P<mid>\d+)-)?(?P<n>\d+)$")


def fail(step, detail):
    print(f"{step}: failed")
    print(detail, file=sys.stderr)
    sys.exit(1)


def parse_args(argv):
    """第 1 引数のリポジトリの直下と、第 2 引数の `--dry-run` を返す（不正なら None）。"""
    if not argv or len(argv) > MAX_ARGS or (len(argv) == MAX_ARGS and argv[1] != "--dry-run"):
        return None
    root = Path(argv[0])
    if not (root / ".git").exists():
        return None
    return root, len(argv) == MAX_ARGS


def er_schema_ref(dev_docs):
    """`dev-docs.yaml` の `er` の行の `schema.ref` を返す（無ければ None）。"""
    for d in dev_docs.get("documents") or []:
        if d.get("id") == "er" and isinstance(d.get("schema"), dict):
            return d["schema"].get("ref")
    return None


def dirty_paths(root, paths):
    """`paths`（リポジトリの直下からの相対パス）のうち、未 commit の変更があるものを返す。"""
    r = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in r.stdout.splitlines() if line.strip()]


def er_files(root):
    folder = root / ER_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*.yaml") if p.name != "index.yaml")


def ignored_rule(root):
    """`docs/data/` のファイルを除外する .gitignore の行を返す（除外されなければ None）。"""
    probe = str(DATA_DIR / "probe.yaml")
    r = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-v", "--no-index", probe],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def strip_code(value):
    if value is None:
        return None
    value = str(value).strip()
    if value.startswith("`") and value.endswith("`") and value.count("`") == CODE_QUOTES:
        value = value[1:-1]
    return value.strip('"') or None


def logical_type(name, column_type):
    t = str(column_type or "").lower()
    if t in ("bool", "boolean"):
        return "bool"
    if any(k in t for k in ("int", "serial", "number")):
        return "int"
    if any(k in t for k in ("timestamp", "datetime", "date")) or name.endswith("_at"):
        return "datetime"
    if t in ("object", "json", "jsonb", "map"):
        return "object"
    if t in ("array", "list") or t.endswith("[]"):
        return "array"
    return "string"


def field_key(name):
    """カラム名をデータの設計書のキーにする（`fields[...]` で指せない文字は `_` にする）。"""
    return re.sub(r"[\[\]\s`]+", "_", str(name)).strip("_") or "value"


def data_mid(er_docs, data_docs):
    """作成するデータの設計書の ID の中の番号を、既存の ER 図・データの設計書の ID から決める（`{種類}-{番号}` の形なら空文字）。"""
    matches = [m for doc in list(data_docs) + list(er_docs) if (m := ID_RE.match(str(doc.get("id", ""))))]
    for m in matches:
        if m.group("mid"):
            return m.group("mid")
    return "" if matches else None


def build_data_doc(doc_id, er_id, table):
    fields = []
    for c in table.get("columns") or []:
        f = {
            "key": field_key(c["name"]),
            "title": str(c.get("title") or c["name"]),
            "type": logical_type(str(c["name"]), c.get("type")),
            "description": str(c.get("description") or c.get("title") or c["name"]),
        }
        if c.get("not_null"):
            f["required"] = True
        ex = strip_code(c.get("example"))
        if ex:
            f["example"] = ex
        if c.get("primary_key") or c.get("unique") is True:
            f["unique"] = "全体"
        fields.append(f)
    doc = {
        "id": doc_id,
        "visibility": "internal",
        "title": f"データ: {table.get('title') or table['name']}",
        "lead": str(table.get("summary") or table.get("title") or table["name"]).rstrip("。")
        + "。",
        "datastore": str(table.get("datastore") or "-"),
        "fields": fields,
    }
    if "]" not in str(table["name"]):
        doc["refs"] = [f"{er_id}#tables[{table['name']}]"]
    return doc
