"""コメントを保った YAML の読み書き（ruamel.yaml）と、キーの追加・削除でのコメントの付け替え・レイヤーの重ね合わせ。"""

from __future__ import annotations

import copy
import io
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from voice_paste.shared.errors import SettingsError

YAML_WIDTH: int = 4096
"""長い値を折り返さないための、書くときの 1 行の幅。"""

MAP_TRAILING_SLOT: int = 2
"""CommentedMap の ca.items[キー] で、そのキーの後ろのコメント（行末のコメントと、次のキーの前のコメントと空行）が入る位置。"""

SEQ_TRAILING_SLOT: int = 0
"""CommentedSeq の ca.items[添字] で、その要素の後ろのコメントが入る位置。"""

_YAML11 = YAML(typ="safe")
_YAML11.version = (1, 1)
"""YAML 1.1 で読むと文字列のままかを確かめるための YAML（読むだけに使う）。"""


def _is_ambiguous(value: str) -> bool:
    """YAML 1.1 で引用符なしに読むと文字列でなくなるか（読めないものを含む）。"""
    try:
        return not isinstance(_YAML11.load(value), str)
    except YAMLError:
        return True


def _represent_str(representer: Any, value: str) -> Any:
    """YAML 1.1 で文字列でなくなる値（yes・on・数・`*` で始まる値など）は単引用符で囲んで書く。"""
    style = "'" if _is_ambiguous(value) else None
    return representer.represent_scalar("tag:yaml.org,2002:str", value, style=style)


def make_yaml() -> YAML:
    """コメントと引用符を保って読み書きする YAML を、字下げと引用符の決まりを当てて返す。"""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = YAML_WIDTH
    yaml.representer.add_representer(str, _represent_str)
    return yaml


# === 読み書き ===


def read_yaml_document(path: Path) -> CommentedMap:
    """YAML のファイルを、コメントを保った文書として UTF-8 で読む。無ければ空の文書を返す。"""
    # 1. 無いファイルは空の文書
    if not path.exists():
        return CommentedMap()

    # 2. UTF-8 で読み、解釈する
    try:
        loaded = make_yaml().load(path.read_text(encoding="utf-8"))
    except YAMLError as error:
        raise SettingsError(
            f"設定ファイルを読めない（{path}: {_describe_yaml_error(error)}）", paths=(path,)
        ) from error
    except UnicodeDecodeError as error:
        raise SettingsError(f"設定ファイルを読めない（{path}: {error}）", paths=(path,)) from error
    # 空のファイルは空の文書
    if loaded is None:
        return CommentedMap()
    # 一番上が表でないファイルは断る
    if not isinstance(loaded, CommentedMap):
        raise SettingsError(f"設定ファイルを読めない（{path}: 一番上が表でない）", paths=(path,))
    return loaded


def _describe_yaml_error(error: YAMLError) -> str:
    """読めない YAML の理由を、分かれば行・列（1 始まり）を添えて返す。"""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    # 位置が分からない: 理由だけ
    if mark is None:
        return str(problem)
    return f"{mark.line + 1}行目 {mark.column + 1}列目: {problem}"


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """YAML のファイルを、コメントを持たない素の dict として読む。無ければ空の dict を返す。"""
    return _to_plain(read_yaml_document(path))


def _to_plain(value: Any) -> Any:
    """ruamel.yaml の表・一覧・値を、素の dict・list・値へ再帰で変える。"""
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    # bool は int の派生のため先に見る
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def write_yaml_document(path: Path, document: Mapping[str, Any]) -> None:
    """文書か dict を UTF-8 の YAML として、同じフォルダの一時ファイルに書いてから置き換える。"""
    stream = io.StringIO()
    make_yaml().dump(_to_commented(document), stream)

    # 1. 親のフォルダを作る
    path.parent.mkdir(parents=True, exist_ok=True)
    # 2. 同じフォルダの一時ファイルへ書き、置き換える（置き換えられなければ一時ファイルを削除する）
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(stream.getvalue())
        temp_path = Path(temp_file.name)
    try:
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _to_commented(value: Any) -> Any:
    """素の dict・list を、コメントを持てる CommentedMap・CommentedSeq へ再帰で変える（既にそうならそのまま）。"""
    if isinstance(value, CommentedMap | CommentedSeq):
        return value
    if isinstance(value, Mapping):
        return CommentedMap((key, _to_commented(item)) for key, item in value.items())
    if isinstance(value, list):
        return CommentedSeq(_to_commented(item) for item in value)
    return value


# === 後ろのコメントの付け替え ===
#
# ruamel.yaml は、キーの前のコメントと空行を、直前のキー（入れ子なら一番奥の最後の要素）の後ろのコメントとして持つ。
# 後ろのコメントの値は「行末の部分」と「続く行」に分けて扱う。
# 行末の部分は、行末のコメントがあれば `# …\n`、無ければ `\n`（値の行の終わり）。続く行は、次のキーの前の空行とコメント。
# キーを追加・削除するときは続く行だけを前後のキーへ移し、行末のコメントは元のキーに残す。


def _split_following(slot: list[Any], index: int) -> str | None:
    """後ろのコメントから続く行を取り外して返す。行末のコメントは残し、無ければ後ろのコメントごと外す。"""
    token = slot[index]
    if token is None:
        return None
    head, newline, following = token.value.partition("\n")
    # 行末のコメントがあれば、その行だけを残す
    if head.strip():
        token.value = head + newline
    else:
        slot[index] = None
    return following or None


def _new_comment(value: str) -> CommentToken:
    """行の先頭から書くコメントを作る。"""
    return CommentToken(value, CommentMark(0))


def _attach_following(slot: list[Any], index: int, following: str) -> None:
    """続く行を、後ろのコメントの末尾へつなぐ。後ろのコメントが無ければ作る。"""
    token = slot[index]
    # 後ろのコメントが無い: 値の行の終わりに続けて作る
    if token is None:
        slot[index] = _new_comment("\n" + following)
    else:
        token.value += following


def _take_following(node: Any) -> str | None:
    """表・一覧の一番奥の最後の要素から、後ろのコメントの続く行を取り外して返す。"""
    # 表: 最後のキーの値が中身のある表・一覧なら奥へ、そうでなければそのキーの後ろのコメント
    if isinstance(node, CommentedMap) and node:
        last = next(reversed(node))
        if _has_items(node[last]):
            return _take_following(node[last])
        slot = node.ca.items.get(last)
        return None if slot is None else _split_following(slot, MAP_TRAILING_SLOT)
    # 一覧: 最後の要素が中身のある表・一覧なら奥へ、そうでなければその要素の後ろのコメント
    if isinstance(node, CommentedSeq) and node:
        last_index = len(node) - 1
        if _has_items(node[last_index]):
            return _take_following(node[last_index])
        slot = node.ca.items.get(last_index)
        return None if slot is None else _split_following(slot, SEQ_TRAILING_SLOT)
    return None


def _give_following(node: Any, following: str) -> None:
    """表・一覧の一番奥の最後の要素の後ろのコメントへ、続く行をつなぐ。"""
    # 表: 最後のキーの値が中身のある表・一覧なら奥へ、そうでなければそのキーの後ろのコメントへ
    if isinstance(node, CommentedMap) and node:
        last = next(reversed(node))
        if _has_items(node[last]):
            _give_following(node[last], following)
            return
        slot = node.ca.items.setdefault(last, [None, None, None, None])
        _attach_following(slot, MAP_TRAILING_SLOT, following)
    # 一覧: 最後の要素が中身のある表・一覧なら奥へ、そうでなければその要素の後ろのコメントへ
    elif isinstance(node, CommentedSeq) and node:
        last_index = len(node) - 1
        if _has_items(node[last_index]):
            _give_following(node[last_index], following)
            return
        slot = node.ca.items.setdefault(last_index, [None, None])
        _attach_following(slot, SEQ_TRAILING_SLOT, following)


def _has_items(value: Any) -> bool:
    """中身のある表か一覧か。"""
    return isinstance(value, CommentedMap | CommentedSeq) and bool(value)


def _take_key_following(mapping: CommentedMap, key: str) -> str | None:
    """表のキーの値の一番奥（値が中身の無いものならそのキー）から、後ろのコメントの続く行を取り外して返す。"""
    if _has_items(mapping[key]):
        return _take_following(mapping[key])
    slot = mapping.ca.items.get(key)
    return None if slot is None else _split_following(slot, MAP_TRAILING_SLOT)


def _give_key_following(mapping: CommentedMap, key: str, following: str) -> None:
    """表のキーの値の一番奥（値が中身の無いものならそのキー）の後ろのコメントへ、続く行をつなぐ。"""
    if _has_items(mapping[key]):
        _give_following(mapping[key], following)
        return
    slot = mapping.ca.items.setdefault(key, [None, None, None, None])
    _attach_following(slot, MAP_TRAILING_SLOT, following)


# === キーの書き込みと削除 ===


def set_key(document: CommentedMap, key: tuple[str, ...], value: Any) -> None:
    """キーの値を文書に書く。無い表は作り、新しく追加するキーは次のキーの前のコメントより前に置く。"""
    # 1. 途中の表をたどり、無い表は作って追加する
    mapping = document
    for part in key[:-1]:
        child = mapping.get(part)
        if not isinstance(child, CommentedMap):
            child = CommentedMap()
            _put(mapping, part, child)
        mapping = child
    # 2・3. 末尾のキーを書く
    _put(mapping, key[-1], _to_commented(copy.deepcopy(value)))


def _put(mapping: CommentedMap, name: str, value: Any) -> None:
    """表のキーに値を置く。既にあれば値だけを替え、無ければ末尾へ追加して、それまでの最後のキーの後ろのコメントを移す。"""
    # 既にあるキー: 古い値の奥が持っていた後ろのコメントを、新しい値の奥へ付け直して替える（行末のコメントは残る）
    if name in mapping:
        following = _take_following(mapping[name]) if _has_items(mapping[name]) else None
        mapping[name] = value
        if following is not None:
            _give_key_following(mapping, name, following)
        return

    # 無いキー: それまでの最後のキーの後ろのコメントを外してから追加し、追加したキーへ付け直す
    last = next(reversed(mapping), None) if mapping else None
    following = _take_key_following(mapping, last) if last is not None else None
    mapping[name] = value
    if following is not None:
        _give_key_following(mapping, name, following)


def delete_key(document: CommentedMap, key: tuple[str, ...]) -> None:
    """キーを文書から外し、中のキーが無くなった表も外す。外したキーの後ろのコメントは前のキーへ付け直す。"""
    # 1. 途中の表をたどる（キーが無ければ何もしない）
    chain: list[CommentedMap] = [document]
    for part in key[:-1]:
        child = chain[-1].get(part)
        if not isinstance(child, CommentedMap):
            return
        chain.append(child)
    if key[-1] not in chain[-1]:
        return

    # 4. 外すと空になる表は、親から表ごと外す（一番上の文書は空にしてよい）
    depth = len(key) - 1
    while depth > 0 and len(chain[depth]) == 1:
        depth -= 1
    _remove(chain[depth], key[depth])


def _remove(mapping: CommentedMap, name: str) -> None:
    """表からキーを外し、そのキーの後ろのコメントの続く行を前のキー（無ければ表の前のコメント）へ付け直す。"""
    keys = list(mapping.keys())
    index = keys.index(name)
    # 2. 外す前に、外すキーの後ろのコメントの続く行を取り出す（行末のコメントはキーと一緒に消える）
    following = _take_key_following(mapping, name)
    del mapping[name]
    mapping.ca.items.pop(name, None)
    if following is None:
        return

    # 3. 前のキーの後ろへ付け直す。前のキーが無ければ、表の前のコメントの後ろに付ける
    if index > 0:
        _give_key_following(mapping, keys[index - 1], following)
        return
    comment = mapping.ca.comment or [None, []]
    comment[1] = [*(comment[1] or []), _new_comment(following)]
    mapping.ca.comment = comment


# === レイヤー ===


def merge_layers(*layers: Mapping[str, Any]) -> dict[str, Any]:
    """後ろのレイヤーの値で前のレイヤーを上書きした新しい dict を返す。表はキーごとに重ね、一覧と値は丸ごと替える。"""
    merged: dict[str, Any] = {}
    for layer in layers:
        merged = _merge_two(merged, layer)
    return merged


def _merge_two(base: Mapping[str, Any], upper: Mapping[str, Any]) -> dict[str, Any]:
    """base に upper を重ねた新しい dict を返す。"""
    merged = copy.deepcopy(dict(base))
    for key, value in upper.items():
        # 両方が表: キーごとに重ねる
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_two(merged[key], value)
        # 一覧・値: 後ろのレイヤーで丸ごと替える
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def changed_keys(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """2 つの dict で値が違うキーを、表はキーごとにたどって、一覧と値は丸ごと比べて返す。"""
    keys: list[tuple[str, ...]] = []
    names = [*before.keys(), *(name for name in after.keys() if name not in before)]
    for name in names:
        old = before.get(name)
        new = after.get(name)
        # 両方にあって両方が表: 中のキーごとに比べる
        if name in before and name in after and isinstance(old, Mapping) and isinstance(new, Mapping):
            keys.extend((name, *inner) for inner in changed_keys(old, new))
        # 片方にしか無いか、値が違う: そのキーを集める
        elif name not in before or name not in after or old != new:
            keys.append((name,))
    return keys


def diff_from_defaults(values: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    """値のうち既定値と違うキーだけを残した dict を返す。表はキーごとに比べ、一覧と値は丸ごと比べる。"""
    diff: dict[str, Any] = {}
    for key, value in values.items():
        default = defaults.get(key)
        # 両方が表: 中のキーごとに比べ、違うキーがあれば残す（空になった表は含めない）
        if isinstance(value, Mapping) and isinstance(default, Mapping):
            inner = diff_from_defaults(value, default)
            if inner:
                diff[key] = inner
        # 既定値に無いか、一覧・値が違う: 丸ごと残す
        elif key not in defaults or value != default:
            diff[key] = copy.deepcopy(value)
    return diff
