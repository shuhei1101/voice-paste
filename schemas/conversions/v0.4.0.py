"""v0.4.0: 開発コマンドの『静的検査』の節が lint 層を指す。データの図・検討事項の ID・非機能要件とテスト実行方法の要素の id を新しい Schema の形へ写す。設計書に ID を振り、設計書どうしの参照を ID で書く。モジュール構成の設計書を物理ファイルごとに分ける。"""

import posixpath
import re
from collections import defaultdict
from functools import partial
from urllib.parse import unquote

from ruamel.yaml.comments import CommentedMap

from ai_monitor.features.design_docs.convert import ConversionRejected
from ai_monitor.features.design_docs.item_path import element_selectors, parse_item_path
from ai_monitor.features.design_docs.markdown import heading_anchor, render_doc
from ai_monitor.features.design_docs.references import (
    DOC_ID_RE,
    build_doc_id_index,
    find_path_links,
    is_ref_schema,
    next_doc_id,
    path_link_target,
)
from ai_monitor.features.design_docs.schemas import INDEX_KIND, resolve_schema
from ai_monitor.features.design_docs.store import doc_file, to_plain
from ai_monitor.features.design_docs.types import Problem

REF_TYPE = "共通.schema.yaml#/$defs/ref"
LINT_LAYER = "dev/設計書/テスト/テスト実行方法#layers[lint]"
LINT_LAYER_SUFFIX = "#layers[lint]"
DEV_COMMAND = "dev_command"
MODULE_KIND = "module"
# 束ねる設計書を置く、モジュール構成の置き場所の下のフォルダ
BUNDLE_FOLDER = "分類"
# 分けた設計書が要素・テストファイル・補足と別に持つ最上位の項目
TEST_FILES = "test_files"
EXTERNAL_TEST_FILES = "external_test_files"
NOTES = "notes"
# 疎通テストを持つ関数・メソッドが持つ項目と、メソッドの一覧の項目
CONNECTIVITY_TESTS = "connectivity_tests"
METHODS = "methods"
# 参照の型でない文字列で設計書の参照を持つ、非機能要件の要件の出所
NONFUNCTIONAL_KIND = "nonfunctional"
REQUIREMENTS = "requirements"
SOURCE = "source"
# 設計書のパスの末尾の拡張子（`検証.py` の `.py`）
_EXTENSION_RE = re.compile(r"\.[^./]+$")
# 設計書のパスの末尾に続く拡張子の部分（`コメント.js.css` の `.js.css`）
_EXTENSIONS_RE = re.compile(r"(\.[^./]+)+$")
# Markdown のリンク `](…)` と、図の `click … href "…"`
_LINK_RE = re.compile(r'(\]\()([^)\s]+)(\))|(href\s+")([^"]+)(")')
# 項目のパスの先頭の要素（`functions[resolve_ref]`）
_FIRST_ELEMENT_RE = re.compile(r"^[^.\[\]]+\[[^\]]*\]")
# 項目のパスの先頭の補足の節（`notes[features/x.py]` と `notes.name`）
_NOTES_SECTION_RE = re.compile(r"^notes(?:\[(?P<bracket>[^\]]+)\]|\.(?P<dot>.+))$")
_NEW_ID_RE = re.compile(r"([A-Z]+)-(\d+)")
# `id:` のリンクの項目のパスの `.{キー}` に書けない文字
_LINK_UNSAFE_RE = re.compile(r'[\s()"#]')
# データの図のノードの形 → 箱の種類（判定の図の開始・終端は線の向きで決める）
SHAPE_KINDS = {"circle": "process", "cylinder": "store", "stadium": "actor", "diamond": "question"}
# Mermaid の線の書き方のうち、意味の線へ写すもの（他は既定の `flow` にして消す）
LINE_KINDS = {"dotted": "reply"}
# 図の向きの写し方
DIRECTIONS = {"TB": "TD", "BT": "TD", "RL": "LR"}
# Mermaid の多重度の片端の記号 → 両端の多重度
CARDINALITIES = {
    "||": "1",
    "|o": "0..1",
    "o|": "0..1",
    "|{": "1..n",
    "}|": "1..n",
    "o{": "0..n",
    "}o": "0..n",
}
# Mermaid の多重度（`{左}--{右}` か `{左}..{右}`）
_CARDINALITY_RE = re.compile(r"^(?P<left>\S{2})(?:--|\.\.)(?P<right>\S{2})$")
# 外部キーの列の `comment`（`参照: {実体}.{列}`）
_FOREIGN_KEY_COMMENT_RE = re.compile(r"^参照: (?P<entity>.+)\.(?P<column>[^.\s]+)$")
# 要素に `id` を振る種別 → （要素の配列の項目・ID の接頭辞）
ELEMENT_IDS = {"nonfunctional": ("requirements", "NFR"), "test_procedure": ("layers", "TL")}
# 文字列の末尾の検討事項の ID（`（D-313・D-326）`）
_DECISIONS_RE = re.compile(r"（(?P<ids>[A-Z]+-[0-9]+(?:・[A-Z]+-[0-9]+)*)）$")
REFS = "refs"
DECISIONS = "decisions"
# 2 つ以上（物理ファイル・設計書の重なり）
_MULTIPLE = 2


def convert(kind, doc):
    """設計書 1 つを新しい Schema の形へ書き換え、書き換えた項目のパスを返す。"""
    changed = _convert_lint_layer(kind, doc)
    changed += _convert_diagrams(doc, "", tables=doc.get("tables") or [])
    changed += _convert_element_ids(kind, doc)
    changed += _convert_decisions(doc, "")
    return changed


def _convert_lint_layer(kind, doc):
    """『静的検査』の節に `lint` 層への参照が無ければ足す（`commands` は消さない）。"""
    if kind != DEV_COMMAND:
        return []
    changed = []
    for category in doc.get("categories") or []:
        if category.get("name") != "静的検査":
            continue
        refs = category.get("refs")
        if refs is None:
            # `commands` の直後（無ければ末尾）に置いて、Schema の項目の並びに揃える
            position = (
                list(category.keys()).index("commands") + 1
                if "commands" in category
                else len(category)
            )
            category.insert(position, "refs", [LINT_LAYER])
        elif not any(str(ref).endswith(LINT_LAYER_SUFFIX) for ref in refs):
            refs.append(LINT_LAYER)
        else:
            continue
        changed.append("categories[静的検査].refs")
    return changed


def _join(path, key):
    """項目のパスに子のキーをつなぐ。"""
    return f"{path}.{key}" if path else str(key)


def _convert_diagrams(node, path, *, tables):
    """設計書の中のデータの図（フローチャート・状態遷移・ER 図）を新しい形へ書き換える。"""
    changed = []
    if isinstance(node, dict):
        # フローチャート: ノード・辺・枠・向き
        if "nodes" in node and "edges" in node:
            changed += _convert_flowchart(node, path)
        # 状態遷移: 図のノード名を消す
        if "states" in node and "transitions" in node:
            for state in node.get("states") or []:
                if isinstance(state, dict) and "node" in state:
                    del state["node"]
                    changed.append(_join(path, "states"))
        # ER 図: 多重度と元・先の列
        if "entities" in node and "relations" in node:
            changed += _convert_er(node, path, tables=tables)
        for key, child in node.items():
            changed += _convert_diagrams(child, _join(path, key), tables=tables)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            changed += _convert_diagrams(child, f"{path}[{index}]", tables=tables)
    return list(dict.fromkeys(changed))


def _convert_flowchart(value, path):
    """ノードの形を箱の種類へ、線の書き方を意味へ、向きを 2 つへ、1 つの枠を `frame` へ写す。"""
    changed = []
    nodes = [node for node in value.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in value.get("edges") or [] if isinstance(edge, dict)]
    # 判定の図（判定のノードを持つ）は、開始・終端を入る線・出る線の有無で決める
    decision = any(node.get("shape") == "diamond" for node in nodes)
    targets = {str(edge.get("to")) for edge in edges}
    sources = {str(edge.get("from")) for edge in edges}
    for node in nodes:
        if "shape" not in node:
            continue
        shape = node.pop("shape")
        if "kind" not in node and shape in SHAPE_KINDS:
            kind = SHAPE_KINDS[shape]
            if decision and shape == "stadium":
                kind = "start" if str(node.get("id")) not in targets else "result"
                if str(node.get("id")) in sources and str(node.get("id")) in targets:
                    kind = "action"
            node["kind"] = kind
        changed.append(_join(path, "nodes"))
    for edge in edges:
        if "line" in edge:
            line = edge.pop("line")
            if line in LINE_KINDS:
                edge["line"] = LINE_KINDS[line]
            changed.append(_join(path, "edges"))
    if value.get("direction") in DIRECTIONS:
        value["direction"] = DIRECTIONS[value["direction"]]
        changed.append(_join(path, "direction"))
    subgraphs = value.get("subgraphs")
    # 枠が 1 つだけ: `frame` へ写す。2 つ以上は写せないので残す（新しい Schema の検証の誤りになる）
    if isinstance(subgraphs, list) and len(subgraphs) == 1 and isinstance(subgraphs[0], dict):
        position = list(value.keys()).index("subgraphs")
        frame = CommentedMap()
        frame["label"] = subgraphs[0].get("label", subgraphs[0].get("id", ""))
        frame["nodes"] = list(subgraphs[0].get("nodes") or [])
        del value["subgraphs"]
        value.insert(position, "frame", frame)
        changed.append(_join(path, "frame"))
    return changed


def _entity_columns(entity, tables):
    """実体の列（`columns` を持たなければ、`title` か `name` が同じテーブルの列）を返す。"""
    if entity.get("columns"):
        return entity["columns"]
    for table in tables:
        if str(entity.get("name")) in (str(table.get("title")), str(table.get("name"))):
            return table.get("columns") or []
    return []


def _relation_columns(relation, entities, tables):
    """外部キーの列の `参照: {実体}.{列}` から、関連の（元の列・先の列）を返す（読み取れなければ `None`）。"""
    source, target = str(relation.get("from")), str(relation.get("to"))
    by_name = {str(entity.get("name")): entity for entity in entities if isinstance(entity, dict)}
    # 先の実体の外部キーが元の実体を指す
    for column in _entity_columns(by_name.get(target, {}), tables):
        matched = _FOREIGN_KEY_COMMENT_RE.match(str(column.get("comment", "")))
        if matched and matched["entity"] == source:
            return matched["column"], str(column.get("name"))
    # 元の実体の外部キーが先の実体を指す
    for column in _entity_columns(by_name.get(source, {}), tables):
        matched = _FOREIGN_KEY_COMMENT_RE.match(str(column.get("comment", "")))
        if matched and matched["entity"] == target:
            return str(column.get("name")), matched["column"]
    return None


def _convert_er(value, path, *, tables):
    """関連の Mermaid の多重度を両端へ分け、外部キーから元・先の列を入れる。"""
    changed = []
    entities = value.get("entities") or []
    for index, relation in enumerate(value.get("relations") or []):
        if not isinstance(relation, dict) or "cardinality" not in relation:
            continue
        matched = _CARDINALITY_RE.match(str(relation["cardinality"]))
        left = CARDINALITIES.get(matched["left"]) if matched else None
        right = CARDINALITIES.get(matched["right"]) if matched else None
        # 読み替えられない多重度は残す（新しい Schema の検証の誤りになる）
        if left is None or right is None:
            continue
        position = list(relation.keys()).index("cardinality")
        del relation["cardinality"]
        relation.insert(position, "from_cardinality", left)
        relation.insert(position + 1, "to_cardinality", right)
        columns = _relation_columns(relation, entities, tables)
        # 読み取れない列は入れない（必須の欠落で検証の誤りになる）。入れる列は `to` の直後に置く
        if columns is not None and "from_column" not in relation:
            after_to = list(relation.keys()).index("to") + 1
            relation.insert(after_to, "from_column", columns[0])
            relation.insert(after_to + 1, "to_column", columns[1])
        changed.append(f"{_join(path, 'relations')}[{index}]")
    return changed


def _convert_element_ids(kind, doc):
    """非機能要件の要件・テスト実行方法のレイヤーのうち `id` の無い要素へ、並びの順に番号を振る。"""
    if kind not in ELEMENT_IDS:
        return []
    key, prefix = ELEMENT_IDS[kind]
    elements = [element for element in doc.get(key) or [] if isinstance(element, dict)]
    numbers = [
        int(matched[2])
        for element in elements
        if (matched := _NEW_ID_RE.fullmatch(str(element.get("id", "")))) and matched[1] == prefix
    ]
    serial = max(numbers, default=0)
    changed = []
    for element in elements:
        if "id" in element:
            continue
        serial += 1
        position = list(element.keys()).index("name") if "name" in element else 0
        element.insert(position, "id", f"{prefix}-{serial}")
        changed.append(f"{key}[{element.get('name', serial)}].id")
    return changed


def _convert_decisions(node, path):
    """`refs` を持つ場所の文字列の項目の末尾の検討事項の ID を、同じ場所の `decisions` へ移す。"""
    changed = []
    if isinstance(node, dict):
        if REFS in node:
            moved = []
            for key, child in list(node.items()):
                matched = _DECISIONS_RE.search(child) if isinstance(child, str) else None
                if matched is None:
                    continue
                node[key] = child[: matched.start()].rstrip()
                moved += matched["ids"].split("・")
            if moved:
                decisions = node.get(DECISIONS)
                # 無ければ `refs` の直後に置く
                if decisions is None:
                    node.insert(list(node.keys()).index(REFS) + 1, DECISIONS, [])
                    decisions = node[DECISIONS]
                decisions.extend(decision for decision in moved if decision not in decisions)
                changed.append(_join(path, DECISIONS))
        for key, child in node.items():
            changed += _convert_decisions(child, _join(path, key))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            changed += _convert_decisions(child, f"{path}[{index}]")
    return changed


def _id_serials(ids):
    """持っている ID の、接頭辞ごとの連番の最大値を返す。"""
    serials = {}
    for doc_id in ids.by_id:
        matched = _NEW_ID_RE.fullmatch(doc_id)
        if matched:
            prefix = matched.group(1)
            serials[prefix] = max(serials.get(prefix, 0), int(matched.group(2)))
    return serials


def _new_id(prefix, *, number, ids, serials, reserved):
    """新しい ID を作る（作業 PR の番号が無ければ `{接頭辞}-{連番}`、あれば `{接頭辞}-{番号}-{連番}`）。"""
    if number is None:
        # 作業 PR の番号が無いときの連番は、接頭辞ごとに持っている ID の最大の次から
        serials[prefix] = serials.get(prefix, 0) + 1
        new_id = f"{prefix}-{serials[prefix]}"
    else:
        new_id = next_doc_id(ids, prefix=prefix, number=number, reserved=reserved)
    reserved.append(new_id)
    return new_id


def _assign_ids(docs, catalog, number):
    """ID の接頭辞を持つ種別で `id` の無い設計書へ、設計書のパスの順に ID を振る。"""
    changed = {}
    ids = build_doc_id_index(docs)
    reserved = []
    serials = _id_serials(ids)
    for doc_path in sorted(docs):
        doc = docs[doc_path]
        kind = catalog.kind_for_path(doc_file(doc_path))
        if kind is None or kind.id_prefix is None or "id" in doc:
            continue
        new_id = _new_id(kind.id_prefix, number=number, ids=ids, serials=serials, reserved=reserved)
        # `id` は最上位の `title` の直前に置く
        position = list(doc.keys()).index("title") if "title" in doc else 0
        doc.insert(position, "id", new_id)
        changed.setdefault(doc_path, []).append("id")
    return changed


def _as_id_ref(value, ids):
    """`{設計書のパス}#{項目のパス}` を、参照先の ID の `{ID}#{項目のパス}` にする（そうでなければ None）。"""
    if not isinstance(value, str) or "#" not in value:
        return None
    holder, item_path = value.split("#", 1)
    # 同じ設計書の中の参照と、既に ID で書いた参照はそのまま
    if holder == "" or DOC_ID_RE.fullmatch(holder):
        return None
    doc_id = ids.by_path.get(holder)
    return None if doc_id is None else f"{doc_id}#{item_path}"


def _rewrite_value(owner, position, rewrite):
    """参照の型の値（文字列か文字列のリスト）を `rewrite` で書き換え、書き換えたかを返す。"""
    value = owner[position]
    if isinstance(value, list):
        rewritten = False
        for index, element in enumerate(value):
            new_value = rewrite(element)
            if new_value is not None:
                value[index] = new_value
                rewritten = True
        return rewritten
    new_value = rewrite(value)
    if new_value is None:
        return False
    owner[position] = new_value
    return True


def _element_path(path, schema, index, element):
    """リストの要素の項目のパス（`x-key` の値で指せるときはその値、無ければ添字）。"""
    key = schema.get("x-key")
    if key and hasattr(element, "get") and element.get(key) is not None:
        return f"{path}[{element.get(key)}]"
    return f"{path}[#{index}]"


def _walk_refs(owner, position, schema, path, registry, rewrite, found):
    """Schema をたどって参照の型の値を見つけ、書き換えた項目のパスを `found` に足す（`x-key` の無いリストの中も辿る）。"""
    value = owner[position]
    schema = resolve_schema(schema, registry=registry)
    # 参照の型そのものか、その配列
    if is_ref_schema(schema) or schema.get("x-ref-of") == REF_TYPE:
        if _rewrite_value(owner, position, rewrite) and path not in found:
            found.append(path)
        return
    if hasattr(value, "keys"):
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties")
        for key in list(value.keys()):
            child = properties.get(key)
            if child is None and hasattr(additional, "get"):
                child = additional
            if child is not None:
                _walk_refs(
                    value, key, child, f"{path}.{key}" if path else key, registry, rewrite, found
                )
    elif isinstance(value, list) and hasattr(schema.get("items"), "get"):
        for index, element in enumerate(value):
            _walk_refs(
                value,
                index,
                schema["items"],
                _element_path(path, schema, index, element),
                registry,
                rewrite,
                found,
            )


def _rewrite_refs(docs, catalog, rewrite_for):
    """参照の型の値を、設計書ごとの `rewrite_for(設計書のパス)` が返す書き換えで書き換える。"""
    changed = {}
    for doc_path in sorted(docs):
        kind = catalog.kind_for_path(doc_file(doc_path))
        if kind is None:
            continue
        rewrite = rewrite_for(doc_path)
        found = []
        for key in list(docs[doc_path].keys()):
            child = (kind.schema.get("properties") or {}).get(key)
            if child is not None:
                _walk_refs(docs[doc_path], key, child, key, catalog.registry, rewrite, found)
        if found:
            changed[doc_path] = found
    return changed


def _rewrite_sources(docs, catalog, ids):
    """非機能要件の要件の出所（参照の型でない文字列）のうち、設計書のパスの参照を ID の参照へ書き換える。"""
    changed = {}
    for doc_path in sorted(docs):
        kind = catalog.kind_for_path(doc_file(doc_path))
        if kind is None or kind.kind != NONFUNCTIONAL_KIND:
            continue
        requirements = docs[doc_path].get(REQUIREMENTS)
        if not isinstance(requirements, list):
            continue
        schema = resolve_schema(
            (kind.schema.get("properties") or {}).get(REQUIREMENTS) or {},
            registry=catalog.registry,
        )
        found = []
        for index, element in enumerate(requirements):
            if not hasattr(element, "get"):
                continue
            # URL と、参照先の設計書が無いパスの参照は None が返り、そのまま残す
            new_value = _as_id_ref(element.get(SOURCE), ids)
            if new_value is None:
                continue
            element[SOURCE] = new_value
            found.append(f"{_element_path(REQUIREMENTS, schema, index, element)}.{SOURCE}")
        if found:
            changed[doc_path] = found
    return changed


def _has_connectivity_tests(element):
    """要素自身か、その `methods` の要素が疎通テストを持つかを返す。"""
    if element.get(CONNECTIVITY_TESTS):
        return True
    methods = element.get(METHODS)
    return isinstance(methods, list) and any(
        hasattr(method, "get") and method.get(CONNECTIVITY_TESTS) for method in methods
    )


def _test_name(test_file):
    """テストファイル名から拡張子とテストの接頭辞・接尾辞（`test_`・`_test`・`.test`・`.spec`）を除いた名前を返す。"""
    name = _EXTENSION_RE.sub("", posixpath.basename(test_file))
    return re.sub(r"^test_|_test$|\.test$|\.spec$", "", name)


def _match_external_test_file(test_file, containers):
    """疎通テストのファイルが物理ファイル名に当たらないとき、設計書の疎通テストを持つ物理ファイルから選ぶ。

    1 つならそれを、2 つ以上なら物理ファイルのフォルダ名がテストの名前に当たるものを返す（決まらなければ None）。
    """
    if len(containers) == 1:
        return containers[0]
    name = _test_name(test_file)
    same = [c for c in containers if posixpath.basename(posixpath.dirname(c)) == name]
    return same[0] if len(same) == 1 else None


def _match_test_file(test_file, containers):
    """テストファイルのディレクトリと名前から、対応する物理ファイル（`container`）を 1 つ選ぶ（決まらなければ None）。"""
    name = _test_name(test_file)
    test_dir = posixpath.dirname(test_file)
    matched = []
    for container in containers:
        # 物理ファイル名から拡張子と前後の `__` を除いた名前が同じ候補
        base = _EXTENSION_RE.sub("", posixpath.basename(container)).strip("_")
        if base != name:
            continue
        # テストファイルのディレクトリが、物理ファイルのディレクトリ（空なら全てに当たる）で終わる候補
        container_dir = posixpath.dirname(container)
        if (
            container_dir
            and test_dir != container_dir
            and not test_dir.endswith(f"/{container_dir}")
        ):
            continue
        matched.append((len(container_dir), container))
    if not matched:
        return None
    longest = max(length for length, _ in matched)
    best = [container for length, container in matched if length == longest]
    # ディレクトリの一致が最も長いものが 1 つならそれを返す
    return best[0] if len(best) == 1 else None


def _anchor(text):
    """見出しと同じ規則（英字を小文字にし、空白を `-` にし、`-`・`_` 以外の記号を除く）でアンカーを作る。"""
    lowered = re.sub(r"\s", "-", text.lower())
    return "".join(char for char in lowered if char.isalnum() or char in "-_")


def _map_strings(node, rewrite):
    """辞書・リストの中の文字列の値を `rewrite` で書き換え、書き換えたかを返す（キーは書き換えない）。"""
    changed = False
    entries = node.items() if hasattr(node, "items") else enumerate(node)
    for position, value in list(entries):
        if isinstance(value, str):
            new_value = rewrite(value)
            if new_value != value:
                # 文字列の型（ブロック形式など）を保つ
                node[position] = new_value if type(value) is str else type(value)(new_value)
                changed = True
        elif isinstance(value, dict | list):
            changed = _map_strings(value, rewrite) or changed
    return changed


def _rewrite_links(docs, *, moved_from, targets):
    """分けた設計書を指すリンクと、移した中身の相対リンクを、分けた先の置き場所から見たパスへ書き直す。"""
    changed = {}
    for doc_path in sorted(docs):
        old_path = moved_from.get(doc_path, doc_path)
        old_folder = posixpath.dirname(old_path)
        new_folder = posixpath.dirname(doc_path)

        def resolve(
            match,
            *,
            doc_path=doc_path,
            old_path=old_path,
            old_folder=old_folder,
            new_folder=new_folder,
        ):
            """リンク 1 つを書き直す（書き直さないものはそのまま返す）。"""
            groups = match.groups()
            head, target, tail = groups[:3] if groups[1] is not None else groups[3:]
            path_part, _, anchor = target.partition("#")
            # `#` で始まるリンクと `.yaml` へのリンクだけを引く
            if path_part and not path_part.endswith(".yaml"):
                return match.group(0)
            if path_part.startswith(("http://", "https://")):
                return match.group(0)
            # 書かれた設計書の元のフォルダを基準に、リンク先の設計書を解く
            target_old = (
                posixpath.normpath(posixpath.join(old_folder, path_part)).removesuffix(".yaml")
                if path_part
                else old_path
            )
            new_target = target_old
            retargeted = False
            mapping = targets.get(target_old)
            if mapping is not None:
                destination = mapping.get(anchor, mapping.get(""))
                if destination is not None:
                    new_target = destination
                    retargeted = True
            # 書かれた設計書が動かず、向け先も変わらないリンクはそのまま
            if not retargeted and doc_path == old_path:
                return match.group(0)
            if new_target == doc_path:
                # 向け先が書かれた設計書自身なら `#{アンカー}` だけにする
                if not anchor:
                    return match.group(0)
                return f"{head}#{anchor}{tail}"
            relative = posixpath.relpath(f"{new_target}.yaml", new_folder)
            if not relative.startswith("../"):
                relative = f"./{relative}"
            suffix = f"#{anchor}" if anchor else ""
            return f"{head}{relative}{suffix}{tail}"

        if _map_strings(docs[doc_path], lambda text: _LINK_RE.sub(resolve, text)):
            changed[doc_path] = list(docs[doc_path].keys())
    return changed


def _element_lists(kind, catalog):
    """モジュール構成の Schema の、要素（`container` を持つ項目）の一覧の項目を `properties` の順に返す（項目 → `x-key`）。"""
    registry = catalog.registry
    schema = resolve_schema(kind.schema, registry=registry)
    lists = {}
    for key, child in (schema.get("properties") or {}).items():
        child = resolve_schema(child, registry=registry)
        items = child.get("items")
        if child.get("type") != "array" or not hasattr(items, "get"):
            continue
        if "container" in (resolve_schema(items, registry=registry).get("properties") or {}):
            lists[key] = child.get("x-key")
    return lists


def _doc_elements(doc, element_lists):
    """設計書の要素を `(一覧の項目, 要素の項目のパス, 要素)` の並びで返す（`properties` の順・元の並び）。"""
    found = []
    for key, list_key in element_lists.items():
        elements = doc.get(key)
        if not isinstance(elements, list):
            continue
        selectors = element_selectors(elements, list_key)
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            selector = selectors[index]
            found.append(
                (key, f"{key}[{selector if selector is not None else f'#{index}'}]", element)
            )
    return found


def _ordered_doc(values, schema):
    """項目を Schema の `properties` の順に並べた設計書にする（Schema に無い項目は後ろへ）。"""
    order = list(schema.get("properties") or {})
    doc = CommentedMap()
    for key in order:
        if key in values:
            doc[key] = values[key]
    for key, value in values.items():
        if key not in doc:
            doc[key] = value
    return doc


def _bundle_path(folder, doc_path):
    """物理ファイルを 2 つ以上持っていた設計書の、束ねる設計書のパス（拡張子の部分を除く）にする。"""
    relative = doc_path[len(folder) + 1 :]
    return f"{folder}/{BUNDLE_FOLDER}/{_EXTENSIONS_RE.sub('', relative)}"


def _is_module(doc_path, catalog):
    """設計書のパスがモジュール構成の設計書かを返す。"""
    kind = catalog.kind_for_path(doc_file(doc_path))
    return kind is not None and kind.kind == MODULE_KIND


def _split_module_docs(docs, catalog, *, number):
    """モジュール構成の設計書を物理ファイルごとの設計書と束ねる設計書へ分け、参照とリンクを分けた先へ向ける。"""
    kind = catalog.get(MODULE_KIND)
    if kind is None or kind.folder is None:
        return {}
    folder = kind.folder
    element_lists = _element_lists(kind, catalog)
    module_paths = sorted(path for path in docs if _is_module(path, catalog))
    # 設計書ごとに、要素と、その物理ファイル（元の並びで重ねない）を集める
    elements = {path: _doc_elements(docs[path], element_lists) for path in module_paths}
    containers = {
        path: list(
            dict.fromkeys(
                str(element["container"])
                for _, _, element in elements[path]
                if element.get("container")
            )
        )
        for path in module_paths
    }
    # 分ける対象を決める
    targets = []
    for path in module_paths:
        has_missing = any(not element.get("container") for _, _, element in elements[path])
        if elements[path]:
            movable = (
                has_missing
                or len(containers[path]) >= _MULTIPLE
                or path != f"{folder}/{containers[path][0]}"
            )
        else:
            movable = not path.startswith(f"{folder}/{BUNDLE_FOLDER}/")
        if movable:
            targets.append(path)
    if not targets:
        return {}
    # 物理ファイルごとに、元の設計書・要素を集める（対象でない設計書の要素も入れる）
    sources = defaultdict(list)
    by_container = defaultdict(lambda: defaultdict(list))
    problems = []
    for path in module_paths:
        for list_key, element_path, element in elements[path]:
            container = element.get("container")
            if not container:
                if path in targets:
                    problems.append(
                        Problem(
                            file=doc_file(path),
                            item_path=element_path,
                            kind="instance",
                            reason="container がありません",
                        )
                    )
                continue
            container = str(container)
            if path not in sources[container]:
                sources[container].append(path)
            by_container[container][list_key].append((path, element_path, element))
    # 同じ物理ファイルの同じ名前の要素は、中身が一致すれば 1 つにし、違えば誤りにする
    merged = {}
    for container, lists in by_container.items():
        merged[container] = {}
        for list_key, entries in lists.items():
            list_name = element_lists[list_key]
            kept = {}
            for path, element_path, element in entries:
                name = str(element.get(list_name)) if list_name else element_path
                kept.setdefault(name, []).append((path, element_path, element))
            result = []
            for name_entries in kept.values():
                first_plain = to_plain(name_entries[0][2])
                if len({path for path, _, _ in name_entries}) >= _MULTIPLE and any(
                    to_plain(element) != first_plain for _, _, element in name_entries
                ):
                    for path, element_path, _ in name_entries:
                        others = ", ".join(
                            doc_file(other) for other, _, _ in name_entries if other != path
                        )
                        problems.append(
                            Problem(
                                file=doc_file(path),
                                item_path=element_path,
                                kind="instance",
                                reason=f"同じ物理ファイルの要素の中身が違います: {others}",
                            )
                        )
                result.append(name_entries[0])
            merged[container][list_key] = result
    # 設計書のテストファイルを、対応する物理ファイルへ振り分ける
    all_containers = list(sources)
    connective = [
        container
        for container in all_containers
        if any(
            _has_connectivity_tests(element)
            for entries in merged[container].values()
            for _, _, element in entries
        )
    ]
    test_files = defaultdict(list)
    external_files = defaultdict(list)
    for path in targets:
        for field, candidates, destination in (
            (TEST_FILES, all_containers, test_files),
            (EXTERNAL_TEST_FILES, connective, external_files),
        ):
            for test_file in docs[path].get(field) or []:
                container = _match_test_file(str(test_file), candidates)
                if container is None and field == EXTERNAL_TEST_FILES:
                    own = [name for name in containers[path] if name in connective]
                    container = _match_external_test_file(str(test_file), own)
                if container is None:
                    problems.append(
                        Problem(
                            file=doc_file(path),
                            item_path=field,
                            kind="instance",
                            reason=f"テストファイルの振り分け先がありません: {test_file}",
                        )
                    )
                elif str(test_file) not in destination[container]:
                    destination[container].append(str(test_file))
    # ID を引き継ぐ設計書: その場所にあった設計書、無ければ物理ファイルを 1 つだけ持つ設計書 1 つだけから集めたときのその設計書
    heir_of = {}
    for container, source_paths in sources.items():
        if not any(path in targets for path in source_paths):
            continue
        if f"{folder}/{container}" in source_paths:
            heir_of[container] = f"{folder}/{container}"
        elif len(source_paths) == 1 and len(containers[source_paths[0]]) == 1:
            heir_of[container] = source_paths[0]
        else:
            heir_of[container] = None
    # 物理ファイルの設計書へ ID を引き継いだ元の設計書
    heirs = {heir for heir in heir_of.values() if heir is not None}
    # 束ねる設計書にする対象と、そのパス
    bundle_paths = {}
    for path in targets:
        if not elements[path]:
            bundle_paths[path] = f"{folder}/{BUNDLE_FOLDER}/{path[len(folder) + 1 :]}"
        elif len(containers[path]) >= _MULTIPLE or path not in heirs:
            bundle_paths[path] = _bundle_path(folder, path)
    # 束ねる設計書のパスが、他の束ねる設計書か物理ファイルの設計書のパスと重なるものは誤りにする
    bundle_owners = defaultdict(list)
    for path, bundle_path in bundle_paths.items():
        bundle_owners[bundle_path].append(path)
    physical_paths = {f"{folder}/{container}" for container in heir_of}
    for bundle_path, owners in bundle_owners.items():
        clashing = [doc_file(owner) for owner in owners]
        if bundle_path in physical_paths:
            clashing.append(doc_file(bundle_path))
        if len(clashing) < _MULTIPLE:
            continue
        for owner in owners:
            others = ", ".join(file for file in clashing if file != doc_file(owner))
            problems.append(
                Problem(
                    file=doc_file(owner),
                    item_path="",
                    kind="instance",
                    reason=f"束ねる設計書のパスが重なります: {others}",
                )
            )
    # 決められないものがあれば、どの設計書も書き換えずに誤りを全て返す
    if problems:
        raise ConversionRejected(tuple(problems))
    # ID の振り方を用意する
    ids = build_doc_id_index(docs)
    serials = _id_serials(ids)
    reserved = []
    skeleton_keys = {"id", "title", TEST_FILES, EXTERNAL_TEST_FILES, NOTES, *element_lists}
    new_docs = {}
    moved_from = {}
    origins = defaultdict(list)
    # 物理ファイルごとの設計書を作る（対象の設計書の要素を持つ物理ファイルだけ）
    for container, source_paths in sources.items():
        if not any(path in targets for path in source_paths):
            continue
        new_path = f"{folder}/{container}"
        first = source_paths[0]
        heir = heir_of[container]
        values = {}
        values["id"] = docs[heir].get("id") if heir is not None else None
        if values["id"] is None:
            values["id"] = _new_id(
                kind.id_prefix, number=number, ids=ids, serials=serials, reserved=reserved
            )
        values["title"] = f"{docs[first].get('title')} / {posixpath.basename(container)}"
        for field, files in ((TEST_FILES, test_files), (EXTERNAL_TEST_FILES, external_files)):
            if files.get(container):
                values[field] = list(files[container])
        for list_key in element_lists:
            entries = merged[container].get(list_key)
            if entries:
                values[list_key] = [element for _, _, element in entries]
        notes = CommentedMap()
        for path in source_paths:
            source_notes = docs[path].get(NOTES) or {}
            # ID を引き継いだ設計書の補足は全て、それ以外は物理ファイルと同じ名前の節を持つ
            for name, text in source_notes.items():
                if (path == heir or name == container) and name not in notes:
                    notes[name] = text
        # ID を引き継いだ設計書の冒頭リード・ディレクトリ構成・構成図などを持つ
        if heir is not None:
            for key, value in docs[heir].items():
                if key not in skeleton_keys and key not in values:
                    values[key] = value
        if notes:
            values[NOTES] = notes
        new_docs[new_path] = _ordered_doc(values, kind.schema)
        moved_from[new_path] = first
        origins[new_path] = list(source_paths)
    new_ids = {path: doc["id"] for path, doc in new_docs.items()}
    # 束ねる設計書を作り、要素の無い設計書を束ねる設計書の置き場所へ移す
    bundles = {}
    for path, bundle_path in bundle_paths.items():
        if not elements[path]:
            new_docs[bundle_path] = docs[path]
            moved_from[bundle_path] = path
            origins[bundle_path] = [path]
            bundles[path] = bundle_path
        else:
            values = {key: value for key, value in docs[path].items() if key not in skeleton_keys}
            values["id"] = docs[path].get("id")
            values["title"] = docs[path].get("title")
            rest = CommentedMap(
                (name, text)
                for name, text in (docs[path].get(NOTES) or {}).items()
                if name not in containers[path]
            )
            if rest:
                values[NOTES] = rest
            new_docs[bundle_path] = _ordered_doc(
                {key: value for key, value in values.items() if value is not None}, kind.schema
            )
            moved_from[bundle_path] = path
            origins[bundle_path] = [path]
            bundles[path] = bundle_path
    # 要素・補足の節が移った先を、元の設計書ごとに引けるようにする
    home = {}
    anchors = defaultdict(dict)
    for container, lists in by_container.items():
        new_path = f"{folder}/{container}"
        if new_path not in new_docs:
            continue
        for entries in lists.values():
            for path, element_path, element in entries:
                home.setdefault((path, element_path), new_path)
                title = element.get("title") or element.get("name")
                if title:
                    anchors[path].setdefault(_anchor(str(title)), new_path)
    for path in targets:
        for name in docs[path].get(NOTES) or {}:
            # 物理ファイルと同じ名前の節はその物理ファイルへ、物理ファイルを 1 つだけ持っていた設計書の節はその物理ファイルへ、それ以外は束ねる設計書へ
            if name in containers[path]:
                home[(path, f"{NOTES}:{name}")] = f"{folder}/{name}"
            elif path in heirs:
                home[(path, f"{NOTES}:{name}")] = f"{folder}/{containers[path][0]}"
            elif path in bundles:
                home[(path, f"{NOTES}:{name}")] = bundles[path]
    link_targets = {}
    for path in targets:
        mapping = dict(anchors.get(path, {}))
        if path in bundles:
            mapping[""] = bundles[path]
        elif containers[path]:
            mapping[""] = f"{folder}/{containers[path][0]}"
        link_targets[path] = mapping
    new_ids.update({path: doc.get("id") for path, doc in new_docs.items()})
    # 対象の設計書を除き、作った設計書を足す
    for path in targets:
        docs.pop(path, None)
    for new_path, doc in new_docs.items():
        docs[new_path] = doc
    new_paths = set(new_docs)
    # 参照を分けた先へ向ける
    split_ids = {}
    for path in targets:
        doc_id = ids.by_path.get(path)
        if doc_id is not None:
            split_ids[doc_id] = path

    def rewrite_for(doc_path):
        """設計書 1 つの参照の値を書き換える関数を返す。"""
        owners = origins.get(doc_path, [])

        def rewrite(value):
            if not isinstance(value, str) or "#" not in value:
                return None
            holder, item_path = value.split("#", 1)
            if holder == "":
                candidates = owners
            elif holder in split_ids:
                candidates = [split_ids[holder]]
            else:
                return None
            segment = _FIRST_ELEMENT_RE.match(item_path)
            if segment is not None:
                key = segment.group(0)
            else:
                notes = _NOTES_SECTION_RE.match(item_path)
                if notes is None:
                    return None
                key = f"{NOTES}:{notes.group('bracket') or notes.group('dot')}"
            for owner in candidates:
                destination = home.get((owner, key))
                if destination is not None:
                    destination_id = new_ids.get(destination)
                    if destination_id is None:
                        return None
                    # 同じ設計書の中の参照は `#` だけのまま、ID で書いた参照は移した先の ID にする
                    if holder == "":
                        return None if destination == doc_path else f"{destination_id}#{item_path}"
                    return None if destination_id == holder else f"{destination_id}#{item_path}"
            return None

        return rewrite

    changed = _rewrite_refs(docs, catalog, rewrite_for)
    link_changed = _rewrite_links(docs, moved_from=moved_from, targets=link_targets)
    for doc_path, paths in link_changed.items():
        changed.setdefault(doc_path, []).extend(
            path for path in paths if path not in changed.get(doc_path, [])
        )
    # 作った設計書は載せない
    return {path: paths for path, paths in changed.items() if path not in new_paths}


def _walk_texts(owner, position, schema, path, registry, rewrite, found):
    """Schema をたどって参照の型でない文字列の値を `rewrite` で書き換え、書き換えた項目のパスを `found` に足す。"""
    value = owner[position]
    schema = resolve_schema(schema, registry=registry)
    # 参照の型の値は書き換えない
    if is_ref_schema(schema) or schema.get("x-ref-of") == REF_TYPE:
        return
    if isinstance(value, str):
        new_value = rewrite(value)
        if new_value != value:
            # 文字列の型（ブロック形式など）を保つ
            owner[position] = new_value if type(value) is str else type(value)(new_value)
            if path not in found:
                found.append(path)
    elif hasattr(value, "keys"):
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties")
        for key in list(value.keys()):
            child = properties.get(key)
            if child is None and hasattr(additional, "get"):
                child = additional
            if child is not None:
                _walk_texts(
                    value, key, child, f"{path}.{key}" if path else key, registry, rewrite, found
                )
    elif isinstance(value, list) and hasattr(schema.get("items"), "get"):
        for index, element in enumerate(value):
            _walk_texts(
                value,
                index,
                schema["items"],
                _element_path(path, schema, index, element),
                registry,
                rewrite,
                found,
            )


def _element_anchors(value, schema, path, registry, anchors):
    """`x-key` を持つリストの要素ごとに、`title` と `x-key` の値のアンカー → 項目のパスの組を `anchors` に足す。"""
    schema = resolve_schema(schema, registry=registry)
    if hasattr(value, "keys"):
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties")
        for key in list(value.keys()):
            child = properties.get(key)
            if child is None and hasattr(additional, "get"):
                child = additional
            if child is not None:
                _element_anchors(
                    value[key], child, f"{path}.{key}" if path else key, registry, anchors
                )
    elif isinstance(value, list) and hasattr(schema.get("items"), "get"):
        key = schema.get("x-key")
        for index, element in enumerate(value):
            element_path = _element_path(path, schema, index, element)
            if key and hasattr(element, "get") and element.get(key) is not None:
                for name in (element.get("title"), element.get(key)):
                    if isinstance(name, str):
                        anchors.setdefault(heading_anchor(name), set()).add(element_path)
            _element_anchors(element, schema["items"], element_path, registry, anchors)


def _link_item_path(item_path):
    """項目のパスを `id:` のリンクに書ける形にする（空白・括弧などを含むキーの段は `[{キー}]` にする。書けなければ None）。"""
    segments = parse_item_path(item_path)
    parts = []
    for index, segment in enumerate(segments):
        text = segment.key if segment.selector is None else f"{segment.key}[{segment.selector}]"
        if index > 0 and _LINK_UNSAFE_RE.search(segment.key):
            # 前の段が選ぶ値を持つと `[...]` を続けられない
            if segments[index - 1].selector is not None or segment.selector is not None:
                return None
            parts[-1] = f"{parts[-1]}[{segment.key}]"
            continue
        parts.append(text)
    return ".".join(parts)


def _element_index(doc, kind, registry):
    """`x-key` を持つリストの要素の論理名・物理名のアンカー → 項目のパスの索引を作る（重なるアンカーの値は None）。"""
    found = {}
    _element_anchors(doc, kind.schema, "", registry, found)
    return {
        anchor: (next(iter(paths)) if len(paths) == 1 else None) for anchor, paths in found.items()
    }


def _anchor_index(doc, kind, registry):
    """設計書のアンカー → 項目のパスの索引を作る（1 つの設計書の中で重なるアンカーの値は None）。"""
    headings = {}
    render_doc(to_plain(doc), kind=kind, registry=registry, headings=headings)
    index = _element_index(doc, kind, registry)
    # 見出しのアンカーは要素のアンカーより優先する
    for item_path, anchor in headings.items():
        if item_path:
            index[anchor] = item_path
    return index


def _id_link(doc_id, item_path):
    """`id:{ID}#{項目のパス}` を返す（重なりありか、リンクに書けない項目のパスなら None）。"""
    if item_path is None:
        return None
    link_path = _link_item_path(item_path)
    return None if link_path is None else f"id:{doc_id}#{link_path}"


def _rewrite_path_links(docs, catalog):
    """本文の `./`・`../` で設計書の YAML を指す Markdown のリンクを、リンク先の ID と項目のパスの `id:` のリンクへ書き換える。"""
    ids = build_doc_id_index(docs)
    indexes = {}
    element_indexes = {}

    def elements_of(doc_path):
        """設計書の要素のアンカーの索引を 1 回だけ作って返す（種別を引けない設計書は空）。"""
        if doc_path not in element_indexes:
            kind = catalog.kind_for_path(doc_file(doc_path))
            element_indexes[doc_path] = (
                {} if kind is None else _element_index(docs[doc_path], kind, catalog.registry)
            )
        return element_indexes[doc_path]

    def anchors_of(doc_path):
        """設計書のアンカーの索引を 1 回だけ作って返す（種別を引けない設計書は空）。"""
        if doc_path not in indexes:
            kind = catalog.kind_for_path(doc_file(doc_path))
            indexes[doc_path] = (
                {} if kind is None else _anchor_index(docs[doc_path], kind, catalog.registry)
            )
        return indexes[doc_path]

    def search_kind(target, anchor):
        """リンク先のパスの種別の全ての設計書で要素のアンカーを引き、当たる項目が 1 つだけならその ID と項目のパスを返す。"""
        kind = catalog.kind_for_path(doc_file(target))
        hits = []
        for doc_path in sorted(docs):
            if doc_path not in ids.by_path or catalog.kind_for_path(doc_file(doc_path)) is not kind:
                continue
            # 節の見出しは設計書をまたいで同じ文言が多いので、要素の論理名・物理名だけで引く
            index = elements_of(doc_path)
            if anchor in index:
                hits.append((doc_path, index[anchor]))
        if len(hits) != 1:
            return None
        return _id_link(ids.by_path[hits[0][0]], hits[0][1])

    def resolve(holder, link):
        """リンク 1 つの書き換え先を返す（書き換えないときは None）。"""
        target = path_link_target(holder, link, catalog=catalog)
        if target is None:
            return None
        if not link.anchor:
            return f"id:{ids.by_path[target]}" if target in ids.by_path else None
        anchor = heading_anchor(unquote(link.anchor))
        if target in docs and target in ids.by_path:
            index = anchors_of(target)
            if anchor in index:
                # 重なりありは種別の全体へ引き直さない
                item_path = index[anchor]
                return _id_link(ids.by_path[target], item_path)
        return search_kind(target, anchor)

    changed = {}
    for doc_path in sorted(docs):
        kind = catalog.kind_for_path(doc_file(doc_path))
        # 目次の行は README の Markdown になるので書き換えない
        if kind is None or kind.kind == INDEX_KIND:
            continue

        def rewrite(text, *, doc_path=doc_path):
            """文字列の中のパスのリンクを後ろから書き換える。"""
            out = text
            for link in reversed(find_path_links(text)):
                value = resolve(doc_path, link)
                if value is not None:
                    out = f"{out[: link.start]}{value}{out[link.end :]}"
            return out

        found = []
        for key in list(docs[doc_path].keys()):
            child = (kind.schema.get("properties") or {}).get(key)
            if child is not None:
                _walk_texts(docs[doc_path], key, child, key, catalog.registry, rewrite, found)
        if found:
            changed[doc_path] = found
    return changed


def convert_all(docs, catalog, *, number):
    """ID の無い設計書に ID を振り、パスで書いた参照を ID で書く参照へ書き換え、モジュール構成の設計書を物理ファイルごとに分ける。"""
    changed = _assign_ids(docs, catalog, number)
    # 振った後の ID の索引で参照を書き換える
    ids = build_doc_id_index(docs)
    for doc_path, paths in _rewrite_refs(
        docs, catalog, lambda _doc_path: partial(_as_id_ref, ids=ids)
    ).items():
        changed.setdefault(doc_path, []).extend(paths)
    # 参照の型でない非機能要件の出所も、同じ ID の索引で書き換える
    for doc_path, paths in _rewrite_sources(docs, catalog, ids).items():
        changed.setdefault(doc_path, []).extend(paths)
    # モジュール構成の設計書を物理ファイルごとに分ける
    for doc_path, paths in _split_module_docs(docs, catalog, number=number).items():
        changed.setdefault(doc_path, []).extend(paths)
    # 分けた後の設計書で、本文のパスのリンクを id: のリンクへ書き換える
    for doc_path, paths in _rewrite_path_links(docs, catalog).items():
        changed.setdefault(doc_path, []).extend(
            path for path in paths if path not in changed.get(doc_path, [])
        )
    # 分けて無くなった設計書は載せない
    return {path: paths for path, paths in changed.items() if path in docs}
