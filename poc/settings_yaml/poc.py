"""PoC: ruamel.yaml でコメントを保った設定の round-trip と settings.toml からの移行を確かめる。

`uv run --no-project --with ruamel.yaml --with tomlkit --with pydantic python poc.py` で流す。
"""

from __future__ import annotations

import copy
import difflib
import io
import locale
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

import ruamel.yaml
import tomlkit
from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap

DEFAULTS_YAML = """\
# 既定値（全てのキー）
hotkeys:
  start: ctrl+alt+space
  cancel: esc
transcription:
  engine: local_whisper
  beam_size: 5
  vad: true
glossary:
  presets:
    - name: 既定
      files:
        - default.csv
strip_phrases:
  - えーと
note: ''
"""

ENV_YAML = """\
# voice-paste の環境の値
# 先頭のコメント

hotkeys:
  # 録音開始
  start: ctrl+shift+r  # 行末のコメント
  cancel: f12

# 文字起こし
transcription:
  beam_size: 3
  # VAD の切り替え
  vad: false

# 末尾のコメント
"""

LOCAL_YAML = """\
# この checkout だけの値
hotkeys:
  start: ctrl+alt+b
"""

SPECIAL_STRINGS = ["*", "yes", "no", "on", "off", "0123", "123", "1.5", "a: b", "日本語の文言", "null", "~", "true", "- x", "#x"]

TOML_TEXT = """\
# 前のバージョンの設定
note = "移行のメモ"

[hotkeys]
start = "ctrl+shift+r"
cancel = "esc"

[transcription]
engine = "openai"
beam_size = 5
vad = false

[glossary]
[[glossary.presets]]
name = "既定"
files = ["default.csv", "extra.csv"]
"""


class Hotkeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    cancel: str


class Transcription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str
    beam_size: int
    vad: bool


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    files: list[str]


class Glossary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presets: list[Preset]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hotkeys: Hotkeys
    transcription: Transcription
    glossary: Glossary
    strip_phrases: list[str]
    note: str


_YAML11 = YAML(typ="safe")
_YAML11.version = (1, 1)


def _represent_str(representer: Any, value: str) -> Any:
    """YAML 1.1 で読むと文字列でなくなる文字列（yes・on など）は引用符で囲んで書く。"""
    plain = representer.represent_scalar("tag:yaml.org,2002:str", value)
    try:
        ambiguous = not isinstance(_YAML11.load(value), str)
    except YAMLError:
        ambiguous = True
    if ambiguous:
        plain.style = "'"
    return plain


def new_yaml() -> YAML:
    """コメントを保つ round-trip の YAML を返す（任意のオブジェクトは組み立てない）。"""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.representer.add_representer(str, _represent_str)
    return yaml


def load_text(text: str) -> Any:
    """文字列の YAML を読む。"""
    return new_yaml().load(text)


def dump_text(data: Any) -> str:
    """YAML を文字列に書く。"""
    buf = io.StringIO()
    new_yaml().dump(data, buf)
    return buf.getvalue()


def to_plain(value: Any) -> Any:
    """ruamel・tomlkit の型を素の dict・list・値へ畳む。"""
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
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


def deep_merge(base: dict, over: dict) -> dict:
    """表はキーごとに重ね、一覧と値は丸ごと後のレイヤーで置き換える。"""
    result = copy.deepcopy(base)
    for key, value in over.items():
        # 両方が表: キーごとに重ねる
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        # 一覧・値: 後のレイヤーで丸ごと置き換える
        else:
            result[key] = copy.deepcopy(value)
    return result


def diff_from_defaults(values: dict, defaults: dict) -> dict:
    """既定値と違うキーだけを返す。表はキーごと、一覧は丸ごとで比べる。"""
    result: dict = {}
    for key, value in values.items():
        default = defaults.get(key)
        # 両方が表: 中のキーごとに比べ、違うキーがあれば残す
        if isinstance(value, dict) and isinstance(default, dict):
            sub = diff_from_defaults(value, default)
            if sub:
                result[key] = sub
        # 一覧・値: 丸ごと比べる
        elif value != default:
            result[key] = value
    return result


def add_key_keep_comments(mapping: CommentedMap, key: str, value: Any) -> None:
    """キーを末尾に追加し、それまで最後のキーが持っていた後ろのコメントを追加したキーへ移す。"""
    last = next(reversed(mapping), None) if mapping else None
    mapping[key] = value
    # 最後のキーが後ろのコメントを持っていない: 移すものが無い
    if last is None:
        return
    # 最後のキーの値が表なら、その中の最後のキーが持つ後ろのコメントを取り外す
    trailing = _pop_trailing(mapping[last])
    if trailing is None:
        slot = mapping.ca.items.get(last)
        if slot is None or slot[2] is None:
            return
        trailing, slot[2] = slot[2], None
    # 値が表・一覧のときは、その中の最後の要素の後ろへ移す
    if isinstance(value, (dict, list)):
        _attach_trailing(value, trailing)
    else:
        mapping.ca.items.setdefault(key, [None, None, None, None])[2] = trailing


def _attach_trailing(node: Any, trailing: Any) -> None:
    """表・一覧の最後の要素へ後ろのコメントをつなぐ。"""
    if isinstance(node, CommentedMap) and node:
        last = next(reversed(node))
        if isinstance(node[last], (dict, list)) and node[last]:
            _attach_trailing(node[last], trailing)
        else:
            node.ca.items.setdefault(last, [None, None, None, None])[2] = trailing
    elif isinstance(node, list) and node:
        if isinstance(node[-1], (dict, list)) and node[-1]:
            _attach_trailing(node[-1], trailing)
        else:
            node.ca.items.setdefault(len(node) - 1, [None, None])
            slot = node.ca.items[len(node) - 1]
            slot[0] = trailing


def _pop_trailing(node: Any) -> Any:
    """表の中の最後のキーが持つ後ろのコメントを取り外して返す（入れ子は奥まで辿る）。"""
    if not isinstance(node, CommentedMap) or not node:
        return None
    last = next(reversed(node))
    inner = _pop_trailing(node[last])
    if inner is not None:
        return inner
    slot = node.ca.items.get(last)
    if slot is None or slot[2] is None:
        return None
    trailing, slot[2] = slot[2], None
    return trailing


def delete_key_keep_comments(mapping: CommentedMap, key: str) -> None:
    """キーを外し、そのキーが持っていた後ろのコメントを前のキーへ移す。"""
    keys = list(mapping.keys())
    index = keys.index(key)
    slot = mapping.ca.items.pop(key, None)
    # 表を外すときは、表の中の最後のキーが持つ後ろのコメントを持ち出す
    nested = _pop_trailing(mapping[key])
    del mapping[key]
    trailing = [None, None, nested, None] if nested is not None else slot
    # 外したキーが後ろのコメントを持っていない: 移すものが無い
    if trailing is None or trailing[2] is None:
        return
    # 前のキーの値が表・一覧: その中の最後の要素の後ろへ、元のコメントに続けてつなぐ
    if index > 0 and isinstance(mapping[keys[index - 1]], (dict, list)):
        prev_value = mapping[keys[index - 1]]
        existing = _pop_trailing(prev_value)
        if existing is not None:
            existing.value += trailing[2].value
            _attach_trailing(prev_value, existing)
        else:
            _attach_trailing(prev_value, trailing[2])
    # 前のキーの値がスカラー: 前のキーの後ろのコメントへつなぐ
    elif index > 0:
        prev_slot = mapping.ca.items.setdefault(keys[index - 1], [None, None, None, None])
        if prev_slot[2] is None:
            prev_slot[2] = trailing[2]
        else:
            prev_slot[2].value += trailing[2].value
    # 先頭のキーを外した: 表の前のコメントへつなぐ
    else:
        mapping.ca.comment = mapping.ca.comment or [None, []]
        mapping.ca.comment[1] = (mapping.ca.comment[1] or []) + [trailing[2]]


def changed_lines(before: str, after: str) -> list[str]:
    """変わった行だけを ndiff の形で返す。"""
    return [line for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line[:1] in "+-"]


results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    """観点ごとの結果を控える。"""
    results.append((name, ok, detail))


def check_change() -> None:
    """値を変えて書き、変えた行だけが変わるか。"""
    data = load_text(ENV_YAML)
    data["hotkeys"]["start"] = "ctrl+alt+r"
    after = dump_text(data)
    changed = changed_lines(ENV_YAML, after)
    others_same = [x for x in ENV_YAML.splitlines() if "start:" not in x] == [x for x in after.splitlines() if "start:" not in x]
    record("値の変更", others_same and len(changed) == 2, f"変わった行: {changed!r}")


def check_add() -> None:
    """入れ子のキーと一覧を追加して書き、既存の行が残るか。"""
    data = load_text(ENV_YAML)
    data["transcription"]["engine"] = "openai"
    data["glossary"] = {"presets": [{"name": "追加", "files": ["a.csv", "b.csv"]}]}
    naive_text = dump_text(data)
    kept = load_text(ENV_YAML)
    add_key_keep_comments(kept["hotkeys"], "pause", "f9")
    add_key_keep_comments(kept["transcription"], "engine", "openai")
    add_key_keep_comments(kept, "glossary", load_text("presets:\n  - name: 追加\n    files:\n      - a.csv\n      - b.csv\n"))
    after = dump_text(kept)
    removed = [line for line in changed_lines(ENV_YAML, after) if line.startswith("-")]
    lines = after.splitlines()
    # 追加したキーが、次の表の見出しのコメントと末尾のコメントより前に入っているか
    order_ok = lines.index("  pause: f9") < lines.index("# 文字起こし") and lines.index("  engine: openai") < lines.index("# 末尾のコメント")
    record(
        "キーの追加",
        not removed and order_ok,
        f"消えた・変わった既存の行: {removed!r}\nそのまま追加したとき:\n{naive_text}\nコメントを移して追加したとき:\n{after}",
    )


def check_delete() -> None:
    """キーを外して書き、ほかのコメントが残るか（del だけと、コメントを移す場合を比べる）。"""
    comments = [line.split("#", 1)[1].strip() for line in ENV_YAML.splitlines() if "#" in line]
    details = []
    ok = True
    for section, key in [("hotkeys", "cancel"), ("transcription", "vad"), ("hotkeys", "start"), ("transcription", "beam_size")]:
        naive = load_text(ENV_YAML)
        del naive[section][key]
        naive_text = dump_text(naive)
        kept = load_text(ENV_YAML)
        delete_key_keep_comments(kept[section], key)
        kept_text = dump_text(kept)
        lost_naive = [c for c in comments if c not in naive_text]
        lost_kept = [c for c in comments if c not in kept_text]
        # 外したキーの行末のコメントは、キーと一緒に消えてよい
        allowed = ["行末のコメント"] if key == "start" else []
        ok = ok and lost_kept == allowed and load_text(kept_text) is not None
        details.append(f"{section}.{key}: del だけで失うコメント={lost_naive} / 移して失うコメント={lost_kept}")
    # 表の中のキーが全て既定値に戻ったら、表ごと外す
    data = load_text(ENV_YAML)
    delete_key_keep_comments(data, "transcription")
    text = dump_text(data)
    nonblank = [x for x in text.splitlines() if x.strip()]
    ok = ok and nonblank[-1] == "# 末尾のコメント" and nonblank[3] == "  # 録音開始" and to_plain(load_text(text)) == {"hotkeys": {"start": "ctrl+shift+r", "cancel": "f12"}}
    details.append(f"transcription を表ごと外した後:\n{text}")
    record("キーの削除", ok, "\n".join(details))


def check_migrate() -> None:
    """settings.toml の既定値と違うキーだけを settings.yaml へ書き、重ねた値が等しいか。"""
    defaults = to_plain(load_text(DEFAULTS_YAML))
    toml_values = tomlkit.parse(TOML_TEXT).unwrap()
    toml_values["strip_phrases"] = SPECIAL_STRINGS
    diff = diff_from_defaults(toml_values, defaults)
    out = Path(tempfile.mkdtemp()) / "settings.yaml"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        new_yaml().dump(diff, f)
    with out.open(encoding="utf-8") as f:
        reloaded = to_plain(new_yaml().load(f))
    same = deep_merge(defaults, reloaded) == deep_merge(defaults, toml_values)
    no_default_keys = "cancel" not in reloaded["hotkeys"] and "beam_size" not in reloaded["transcription"]
    record("移行", same and no_default_keys, f"書いた settings.yaml:\n{out.read_text(encoding='utf-8')}")


def check_special_strings() -> None:
    """特別な意味を持つ文字列が文字列のまま戻るか、引用符なしの * が読めない扱いになるか。"""
    data = CommentedMap(values=list(SPECIAL_STRINGS))
    text = dump_text(data)
    reloaded = list(load_text(text)["values"])
    same = all(type(v) is not bool and isinstance(v, str) for v in reloaded) and reloaded == SPECIAL_STRINGS
    try:
        load_text("strip_phrases:\n  - *\n")
        bare, bare_ok = "読めた", False
    except YAMLError as e:
        bare, bare_ok = f"{type(e).__module__}.{type(e).__name__}", True
    # 既定の YAML 1.2 と別に、YAML 1.1 で読む側から見ても文字列のままか
    yaml11 = YAML(typ="safe")
    yaml11.version = (1, 1)
    reloaded11 = yaml11.load(text)["values"]
    record(
        "特別な意味を持つ文字列",
        same and bare_ok and list(reloaded11) == SPECIAL_STRINGS,
        f"書いた値:\n{text}引用符なしの * を読んだとき: {bare}\nYAML 1.1 で読んだ値: {reloaded11!r}",
    )


def check_layers() -> None:
    """既定値 → 環境の値 → checkout の上書きの順に重ね、モデルで確かめられるか。"""
    merged = deep_merge(deep_merge(to_plain(load_text(DEFAULTS_YAML)), to_plain(load_text(ENV_YAML))), to_plain(load_text(LOCAL_YAML)))
    settings = Settings.model_validate(merged)
    ok = (
        settings.hotkeys.start == "ctrl+alt+b"
        and settings.hotkeys.cancel == "f12"
        and settings.transcription.engine == "local_whisper"
        and settings.transcription.beam_size == 3
        and settings.transcription.vad is False
    )
    record("3 レイヤーの重ね合わせ", ok, repr(settings.model_dump()))


def check_unreadable() -> None:
    """構文の誤りで、捕まえる例外の型と行・列が取れるか。"""
    broken = "hotkeys:\n  start: ctrl+alt+b\n   cancel: esc\n"
    try:
        load_text(broken)
        record("読めない YAML", False, "読めた")
    except YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line={mark.line + 1} column={mark.column + 1}" if mark else "位置なし"
        mro = " > ".join(c.__name__ for c in type(e).__mro__[:4])
        record("読めない YAML", mark is not None, f"{mro} / {where}\n{e}")


def main() -> int:
    """全ての観点を流して結果を出す。"""
    for check in [check_change, check_add, check_delete, check_migrate, check_special_strings, check_layers, check_unreadable]:
        check()
    print(
        f"# {platform.system()} / Python {platform.python_version()} / ruamel.yaml {ruamel.yaml.__version__}"
        f" / preferred encoding={locale.getpreferredencoding(False)}"
    )
    for name, ok, detail in results:
        print(f"## {'OK' if ok else 'NG'} {name}\n{detail}\n")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
