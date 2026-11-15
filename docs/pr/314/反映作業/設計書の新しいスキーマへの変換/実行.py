"""dev-docs.yaml の knowledge のスキーマの ref を統一し、設計書を新しいスキーマへ変換する。"""

import difflib
import importlib.util
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AI_MONITOR,
    BACKUP_NAME,
    COPY_IGNORE,
    DEV_DOCS,
    DOCS_DIR,
    ELEMENT_KEYS,
    FILES_YMLS,
    DIRECTORY_NOTE,
    FROM_VERSION,
    KNOWLEDGE,
    LAYOUT_GLOB,
    LOCAL_SCHEMAS,
    MAX_ROUNDS,
    OS_OVERRIDES_FILE,
    OS_OVERRIDES_KEY,
    PER_ENV_NOTE,
    UPSTREAM_CONVERSION,
    REF_LINE,
    TO_REF,
    VIOLATION,
    design_docs,
    fail,
    git_dir,
    knowledge_refs,
    parse_args,
    unexpected,
    validate_lines,
)
sys.path.insert(0, str(AI_MONITOR / "src"))
from ai_monitor.features.design_docs.item_path import parse_item_path  # noqa: E402
from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.comments import CommentedMap  # noqa: E402
from ruamel.yaml.scalarstring import LiteralScalarString  # noqa: E402

ROOT = Path.cwd()


def yaml_rt():
    """書式を保って読み書きする YAML を返す。"""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def check_prerequisites():
    """スキーマの参照への移行が済み、AI Monitor の変換を流せるかを確かめる。"""
    if not (ROOT / ".git").exists() or not (ROOT / DEV_DOCS).is_file():
        fail("前提確認")
    text = (ROOT / DEV_DOCS).read_text(encoding="utf-8")
    # プロジェクトが持ち続けるスキーマ以外を指す行が残っていれば、参照への移行が済んでいない
    copies = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("schema: schemas/") and line.strip()[len("schema: schemas/") :] not in LOCAL_SCHEMAS
    ]
    if copies or not knowledge_refs(text):
        fail("前提確認", stderr="dev-docs.yaml がスキーマのコピーを指している（反映作業『各プロジェクトのスキーマの参照への移行』の前）")
    left = [p.name for p in (ROOT / "schemas").glob("*.schema.yaml") if p.name not in LOCAL_SCHEMAS]
    if left or (ROOT / "schemas" / "conversions").exists():
        fail("前提確認", stderr="schemas/ にスキーマのコピーか変換が残っている")
    if not (AI_MONITOR / "src" / "ai_monitor" / "design_docs").is_dir():
        fail("前提確認", stderr=f"{AI_MONITOR} に AI Monitor の設計書のコマンドが無い")
    print("前提確認: ok")


def copy_tree(dest):
    """変換と検査が読む範囲を一時フォルダへ写す。"""
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns(*COPY_IGNORE), symlinks=True)
    # 検査が git の作業ツリーを前提にする箇所に備え、.git を指すファイルを置く
    (dest / ".git").write_text(f"gitdir: {git_dir(ROOT)}\n", encoding="utf-8")


def unify_refs(root):
    """dev-docs.yaml の knowledge のスキーマの ref を TO_REF に揃える。"""
    path = root / DEV_DOCS
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        m = REF_LINE.match(line.rstrip("\n"))
        out.append(f"{m.group('head')}{TO_REF}\n" if m else line)
    path.write_text("".join(out), encoding="utf-8")


def find_element(doc, item_path):
    """項目のパスが指す要素を返す（見つからなければ None。パスが無ければ設計書そのもの）。"""
    node = doc
    for segment in parse_item_path(item_path) if item_path else []:
        if not isinstance(node, dict) or segment.key not in node:
            return None
        node = node[segment.key]
        if segment.selector is None:
            continue
        # 一覧の中から、キーの値が selector の要素を選ぶ
        node = next(
            (e for e in node or [] if any(str(e.get(k)) == segment.selector for k in ELEMENT_KEYS if k in e)),
            None,
        )
    return node


def add_implements(root, files_cache, impl, doc_id):
    """実装のコードの行に、設計書を指す implements を足す。足せないときは False を返す。"""
    code = impl.split("#", 1)[0]
    if not (root / code).is_file():
        return False
    for prefix, files_yml in FILES_YMLS.items():
        if not code.startswith(prefix):
            continue
        if files_yml not in files_cache:
            files_cache[files_yml] = yaml_rt().load((root / files_yml).read_text(encoding="utf-8"))
        data = files_cache[files_yml]
        rel = code[len(prefix) :]
        entry = next((e for e in data["files"] if e.get("path") == rel), None)
        # コードの行が無ければ足す
        if entry is None:
            entry = CommentedMap(path=rel)
            data["files"].append(entry)
        related = entry.setdefault("related", [])
        # 同じ設計書を指す implements が無いときだけ足す
        if not any(r.get("to") == doc_id and r.get("type") == "implements" for r in related):
            related.append(CommentedMap(to=doc_id, type="implements"))
        return True
    return False


def move_to_notes(element, title, text):
    """要素の notes の節へ文を移す（元の値の書式を保ち、複数行はブロックで書く）。"""
    if "\n" in str(text) and not isinstance(text, LiteralScalarString):
        text = LiteralScalarString(str(text))
    notes = element.get("notes")
    if notes is None:
        notes = CommentedMap()
        element["notes"] = notes
    notes[title] = text


def load_upstream(work):
    """配布元 v0.4.0 の変換を読み込み、モジュール構成の directory のツリーを読む関数を返す。"""
    source = subprocess.run(
        ["git", "-C", str(AI_MONITOR), "show", UPSTREAM_CONVERSION], capture_output=True, text=True, check=False
    )
    if source.returncode != 0:
        fail("配布元の変換の読み込み", ["git", "-C", AI_MONITOR, "show", UPSTREAM_CONVERSION], source.stderr)
    path = work.parent / "upstream_conversion.py"
    path.write_text(source.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("upstream_conversion", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def layout_order():
    """フォルダ構成のエントリの項目の並びを、knowledge のスキーマから返す。"""
    command = ["git", "-C", str(KNOWLEDGE), "show", f"{TO_REF}:schemas/design/layout.schema.yaml"]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        fail("フォルダ構成のスキーマの読み込み", command, done.stderr)
    return list(YAML(typ="safe").load(done.stdout)["$defs"]["entry"]["properties"])


def os_overrides(root):
    """config/defaults.yaml の OS ごとの上書きを、(環境, 設定のキー, 値) の並びにして返す。"""
    data = YAML(typ="safe").load((root / OS_OVERRIDES_FILE).read_text(encoding="utf-8"))
    rows = []

    def walk(env, prefix, value):
        # 辞書は下の段へ、id を持つ要素の一覧は `{一覧}[{id}].{キー}` で、それ以外は値として持つ
        if isinstance(value, dict):
            for key, child in value.items():
                walk(env, f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(value, list) and value and all(isinstance(e, dict) and "id" in e for e in value):
            for element in value:
                for key, child in element.items():
                    if key != "id":
                        walk(env, f"{prefix}[{element['id']}].{key}", child)
        else:
            rows.append((env, prefix, value))

    for env, overrides in (data.get(OS_OVERRIDES_KEY) or {}).items():
        walk(env, "", overrides)
    return rows


def overrides_for(setting_key, overrides):
    """設定のキーを上書きする (環境, キー, 値) を返す（`{一覧}[].{キー}` は一覧の全ての要素に当てる）。"""
    if "[]" in setting_key:
        head, tail = setting_key.split("[]", 1)
        return [r for r in overrides if r[1].startswith(f"{head}[") and r[1].endswith(f"]{tail}")]
    return [r for r in overrides if r[1] == setting_key]


def rewrite_keys(root, violations, upstream, overrides):
    """knowledge のスキーマが持たないキーを書き換える。"""
    docs = {}
    files_cache = {}
    tree = {}
    for v in violations:
        file = v.group("file")
        if file not in docs:
            docs[file] = yaml_rt().load((root / file).read_text(encoding="utf-8"))
        doc = docs[file]
        element = find_element(doc, v.group("path"))
        if element is None:
            fail("キーの書き換え", stderr=f"{file} に {v.group('path')} が無い")
        key = v.group("key")
        if key == "introduced":
            # 入れた PR の番号は git の履歴が持つ
            pass
        elif key == "implementation":
            # 実装の場所は管理用の YAML の implements で持つ。コードが無ければ notes に残す
            if not add_implements(root, files_cache, str(element[key]), str(doc["id"])):
                move_to_notes(element, "実装の場所", element[key])
        elif key == "directory":
            # 配布元の変換と同じく、ツリーはフォルダ構成の設計書へ、ツリーでない記述は notes へ移す
            rows, text = upstream._split_directory(str(element[key]))
            for row_path, comment in rows:
                upstream._add_row(tree, row_path, comment)
            if text:
                move_to_notes(element, DIRECTORY_NOTE, text)
        elif key == "per_env":
            # OS ごとの上書きがあれば overrides の行にし、無ければ notes へ移す
            rows = overrides_for(str(element["key"]), overrides)
            if rows:
                if doc.get("overrides") is None:
                    doc["overrides"] = []
                for env, override_key, value in rows:
                    if not any(o.get("key") == override_key and env in str(o.get("file")) for o in doc["overrides"]):
                        doc["overrides"].append(
                            CommentedMap(
                                file=f"{OS_OVERRIDES_FILE}（{OS_OVERRIDES_KEY}.{env}）",
                                key=override_key,
                                value=str(value).lower() if isinstance(value, bool) else str(value),
                                description=str(element[key]),
                            )
                        )
            else:
                move_to_notes(element, PER_ENV_NOTE, element[key])
        else:
            # 入力チェックの表に同じ要素があれば、表示位置はそちらが持つ
            checks = {str(c.get("element")) for c in doc.get("input_checks") or []}
            if str(element.get("name")) not in checks:
                move_to_notes(element, "エラーの表示", element[key])
        del element[key]
    if tree:
        merge_layout(root, docs, tree, upstream)
    for file, doc in docs.items():
        with (root / file).open("w", encoding="utf-8") as f:
            yaml_rt().dump(doc, f)
    for files_yml, data in files_cache.items():
        with (root / files_yml).open("w", encoding="utf-8") as f:
            yaml_rt().dump(data, f)


def merge_layout(root, docs, tree, upstream):
    """モジュール構成の directory のツリーのうち、フォルダ構成の設計書に無いエントリだけを足す。"""
    layouts = sorted(root.glob(LAYOUT_GLOB))
    if len(layouts) != 1:
        fail("フォルダ構成の設計書", stderr=f"{LAYOUT_GLOB} が {len(layouts)} 件（1 件だけを想定）")
    file = str(layouts[0].relative_to(root))
    if file not in docs:
        docs[file] = yaml_rt().load(layouts[0].read_text(encoding="utf-8"))
    upstream._merge_entries(docs[file]["entries"], tree, layout_order())


def changed_files(work):
    """一時フォルダで変わったファイルを、リポジトリの直下からのパスで返す。"""
    targets = [DEV_DOCS, *FILES_YMLS.values(), *(p.relative_to(work) for p in (work / DOCS_DIR).rglob("*.yaml"))]
    out = []
    for rel in targets:
        before = (ROOT / rel).read_bytes() if (ROOT / rel).exists() else b""
        if before != (work / rel).read_bytes():
            out.append(Path(rel))
    return out


def plan(work):
    """一時フォルダで ref の統一・変換・キーの書き換えを行い、変わるファイルを返す。"""
    unify_refs(work)
    code, stdout, stderr, command = design_docs(
        ["convert", "--from", FROM_VERSION, "--to", TO_REF], work
    )
    if code != 0:
        fail("変換", command, stderr or stdout)
    print("変換: ok")
    # 検査は 1 つの要素の違反を 1 件ずつ出すため、書き換える違反が無くなるまで繰り返す
    upstream = load_upstream(work)
    overrides = os_overrides(work)
    total = 0
    for _ in range(MAX_ROUNDS):
        violations = [m for line in validate_lines(work) if (m := VIOLATION.match(line))]
        if not violations:
            break
        rewrite_keys(work, violations, upstream, overrides)
        total += len(violations)
    else:
        fail("キーの書き換え", stderr="書き換える違反が残っている")
    print(f"キーの書き換え: {'changed' if total else 'skipped'}（{total} 件）")
    rest = unexpected(validate_lines(work))
    if rest:
        fail("検査", stderr="\n".join(rest))
    print("検査: ok")
    return changed_files(work)


def main():
    dry_run = parse_args(sys.argv[1:])
    if dry_run is None:
        fail("前提確認", stderr=f"引数: {sys.argv[1:]}")
    check_prerequisites()

    # 計画（--dry-run もここを通る）
    with tempfile.TemporaryDirectory(prefix="pr314-convert-") as tmp:
        work = Path(tmp) / "repo"
        copy_tree(work)
        files = plan(work)
        if not files:
            print("設計書の変換: skipped")
            return
        for rel in files:
            before = (ROOT / rel).read_text(encoding="utf-8").splitlines(keepends=True)
            after = (work / rel).read_text(encoding="utf-8").splitlines(keepends=True)
            sys.stdout.writelines(difflib.unified_diff(before, after, str(rel), str(rel)))
        if dry_run:
            print(f"設計書の変換: changed（{len(files)} ファイル）")
            return

        # 適用（退避 → 置き換え）
        backup = git_dir(ROOT) / BACKUP_NAME
        if backup.exists():
            fail("退避", stderr=f"{backup} が既にある")
        for rel in files:
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, backup / rel)
        (backup / "files.txt").write_text("".join(f"{rel}\n" for rel in files), encoding="utf-8")
        print(f"退避: ok（{backup}）")
        for rel in files:
            shutil.copy2(work / rel, ROOT / rel)
    print(f"設計書の変換: changed（{len(files)} ファイル）")


main()
