"""shared/yaml_document.py（read_yaml_document・set_key・delete_key・merge_layers・changed_keys・diff_from_defaults）の単体テスト。"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

DOCUMENT_FILE_NAME = "document.yaml"
"""一時フォルダに置く YAML の文書のファイル名。"""

HOTKEYS_THEN_TRANSCRIPTION = (
    "hotkeys:\n  start: <ctrl>+<alt>+s\n\n# 文字起こし\ntranscription:\n  engine: openai\n"
)
"""hotkeys の表（start だけ）の後ろに「# 文字起こし」のコメントと transcription の表がある文書。"""


def _write_document(tmp_path: Path, text: str) -> Path:
    """一時フォルダに YAML の文書を書き、そのパスを返す。"""
    path = tmp_path / DOCUMENT_FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


# === read_yaml_document ===


def test_read_yaml_document_when_broken(tmp_path: Path) -> None:
    """読めない YAML はパスと行・列を示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.yaml_document import read_yaml_document

    # 準備（3 行目の字下げが崩れたファイル）
    path = _write_document(tmp_path, "hotkeys:\n  start: a\n pause: b\n")

    # 実行・検証
    with pytest.raises(SettingsError, match=r"3行目") as exc_info:
        read_yaml_document(path)
    assert str(path) in str(exc_info.value)


def test_read_yaml_document_when_not_mapping(tmp_path: Path) -> None:
    """一番上が一覧のファイルを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.yaml_document import read_yaml_document

    # 準備
    path = _write_document(tmp_path, "- a\n")

    # 実行・検証
    with pytest.raises(SettingsError, match=DOCUMENT_FILE_NAME):
        read_yaml_document(path)


# === set_key ===


def test_set_key_when_added(tmp_path: Path) -> None:
    """追加したキーが、次の表の見出しのコメントより前に入る（正常系）。"""
    from voice_paste.shared.yaml_document import read_yaml_document, set_key, write_yaml_document

    # 準備
    path = _write_document(tmp_path, HOTKEYS_THEN_TRANSCRIPTION)
    document = read_yaml_document(path)

    # 実行
    set_key(document, ("hotkeys", "pause"), "<ctrl>+<alt>+p")
    write_yaml_document(path, document)

    # 検証
    assert path.read_text(encoding="utf-8") == (
        "hotkeys:\n"
        "  start: <ctrl>+<alt>+s\n"
        "  pause: <ctrl>+<alt>+p\n"
        "\n"
        "# 文字起こし\n"
        "transcription:\n"
        "  engine: openai\n"
    )


def test_set_key_when_nested_table_added(tmp_path: Path) -> None:
    """無い表を作って書く（正常系）。"""
    from voice_paste.shared.yaml_document import (
        read_yaml_document,
        read_yaml_mapping,
        set_key,
        write_yaml_document,
    )

    # 準備（空の文書）
    path = tmp_path / DOCUMENT_FILE_NAME
    document = read_yaml_document(path)

    # 実行
    set_key(document, ("transcription", "local_whisper", "model"), "small")
    write_yaml_document(path, document)

    # 検証
    assert read_yaml_mapping(path) == {"transcription": {"local_whisper": {"model": "small"}}}


def test_set_key_when_existing(tmp_path: Path) -> None:
    """既にあるキーは値だけを替え、行末のコメントを残す（正常系）。"""
    from voice_paste.shared.yaml_document import read_yaml_document, set_key, write_yaml_document

    # 準備
    path = _write_document(tmp_path, "hotkeys:\n  start: a  # 録音の開始\n")
    document = read_yaml_document(path)

    # 実行
    set_key(document, ("hotkeys", "start"), "b")
    write_yaml_document(path, document)

    # 検証
    assert path.read_text(encoding="utf-8") == "hotkeys:\n  start: b  # 録音の開始\n"


# === delete_key ===


def test_delete_key_when_trailing_comment(tmp_path: Path) -> None:
    """外したキーの後ろのコメントと空行が残る（正常系）。"""
    from voice_paste.shared.yaml_document import (
        delete_key,
        read_yaml_document,
        write_yaml_document,
    )

    # 準備
    path = _write_document(
        tmp_path,
        "hotkeys:\n  start: a\n  cancel: c\n\n# 文字起こし\ntranscription:\n  engine: openai\n",
    )
    document = read_yaml_document(path)

    # 実行
    delete_key(document, ("hotkeys", "cancel"))
    write_yaml_document(path, document)

    # 検証
    assert path.read_text(encoding="utf-8") == (
        "hotkeys:\n  start: a\n\n# 文字起こし\ntranscription:\n  engine: openai\n"
    )


def test_delete_key_when_table_emptied(tmp_path: Path) -> None:
    """中のキーが無くなった表を外し、表の後ろのコメントを前の表へ付け直す（正常系）。"""
    from voice_paste.shared.yaml_document import (
        delete_key,
        read_yaml_document,
        read_yaml_mapping,
        write_yaml_document,
    )

    # 準備
    path = _write_document(
        tmp_path,
        "recording:\n"
        "  fade_sec: 1.5\n"
        "hotkeys:\n"
        "  start: a\n"
        "\n"
        "# 文字起こし\n"
        "transcription:\n"
        "  engine: openai\n",
    )
    document = read_yaml_document(path)

    # 実行
    delete_key(document, ("hotkeys", "start"))
    write_yaml_document(path, document)

    # 検証
    text = path.read_text(encoding="utf-8")
    assert "hotkeys" not in text
    assert "# 文字起こし\ntranscription:\n" in text
    assert read_yaml_mapping(path) == {
        "recording": {"fade_sec": 1.5},
        "transcription": {"engine": "openai"},
    }


def test_delete_key_when_missing(tmp_path: Path) -> None:
    """無いキーは何もしない（正常系）。"""
    from voice_paste.shared.yaml_document import delete_key, read_yaml_document

    # 準備（空の文書）
    document = read_yaml_document(tmp_path / DOCUMENT_FILE_NAME)

    # 実行
    delete_key(document, ("hotkeys", "start"))

    # 検証
    assert dict(document) == {}


# === merge_layers ===


def test_merge_layers() -> None:
    """表はキーごと、一覧は丸ごと上書きする（正常系）。"""
    from voice_paste.shared.yaml_document import merge_layers

    # 準備
    base: dict[str, Any] = {"a": {"x": 1, "y": 2}, "l": [1, 2]}
    upper: dict[str, Any] = {"a": {"y": 3}, "l": [9]}
    base_before = copy.deepcopy(base)
    upper_before = copy.deepcopy(upper)

    # 実行
    merged = merge_layers(base, upper)

    # 検証
    assert merged == {"a": {"x": 1, "y": 3}, "l": [9]}
    assert base == base_before
    assert upper == upper_before


# === changed_keys ===


def test_changed_keys() -> None:
    """表の中の違うキーと、一覧の違いを返す（正常系）。"""
    from voice_paste.shared.yaml_document import changed_keys

    # 実行
    keys = changed_keys({"a": {"x": 1, "y": 2}, "l": [1, 2]}, {"a": {"x": 1, "y": 3}, "l": [1]})

    # 検証
    assert keys == [("a", "y"), ("l",)]


# === diff_from_defaults ===


def test_diff_from_defaults() -> None:
    """違うキーだけが残り、既定値に重ねると元に戻る（正常系）。"""
    from voice_paste.shared.yaml_document import diff_from_defaults, merge_layers

    # 準備
    values: dict[str, Any] = {"a": {"x": 1, "y": 3}, "l": [1, 2], "b": {"z": 0}}
    defaults: dict[str, Any] = {"a": {"x": 1, "y": 2}, "l": [1], "b": {"z": 0}}

    # 実行
    diff = diff_from_defaults(values, defaults)

    # 検証
    assert diff == {"a": {"y": 3}, "l": [1, 2]}
    assert merge_layers(defaults, diff) == values
