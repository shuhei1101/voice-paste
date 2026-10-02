"""features/correction/service.py（load_glossary・apply_glossary）の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

CSV_HEADER = "誤変換,正しい表記\n"


@pytest.fixture
def glossary_file(tmp_path: Path) -> Path:
    """一時フォルダの用語集の CSV のパスを返す（ファイルはまだ無い）。"""
    return tmp_path / "yogo.csv"


# === load_glossary ===


def test_load_glossary(glossary_file: Path) -> None:
    """CSV の行を読む（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    glossary_file.write_text(
        f"{CSV_HEADER}くろーどこーど,Claude Code\n\nぎっとはぶ,GitHub\n", encoding="utf-8"
    )

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == [
        GlossaryEntry(wrong="くろーどこーど", right="Claude Code"),
        GlossaryEntry(wrong="ぎっとはぶ", right="GitHub"),
    ]


def test_load_glossary_when_missing(tmp_path: Path) -> None:
    """ファイルが無ければ空を返す（正常系）。"""
    from voice_paste.features.correction.service import load_glossary

    # 実行
    entries = load_glossary(tmp_path / "missing.csv")

    # 検証
    assert entries == []


def test_load_glossary_when_bom(glossary_file: Path) -> None:
    """BOM つきの CSV も列名で読める（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER}くろーど,Claude\n", encoding="utf-8-sig")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == [GlossaryEntry(wrong="くろーど", right="Claude")]


def test_load_glossary_when_blank_cells(glossary_file: Path) -> None:
    """空白を除き、どちらかが空の行を飛ばす（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER} くろーど , Claude \nあいう,\n,えお\n", encoding="utf-8")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == [GlossaryEntry(wrong="くろーど", right="Claude")]


# === apply_glossary ===


def test_apply_glossary() -> None:
    """誤変換を置き換える（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="くろーどこーど", right="Claude Code")]

    # 実行
    text = apply_glossary("今日はくろーどこーどを使う", entries)

    # 検証
    assert text == "今日はClaude Codeを使う"


def test_apply_glossary_when_chained() -> None:
    """前の行で置き換えた結果に次の行を当てる（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="A", right="B"), GlossaryEntry(wrong="B", right="C")]

    # 実行
    text = apply_glossary("A", entries)

    # 検証
    assert text == "C"


def test_apply_glossary_when_no_match() -> None:
    """誤変換を含まなければそのまま返す（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.features.correction.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="くろーどこーど", right="Claude Code")]

    # 実行
    text = apply_glossary("今日は晴れ", entries)

    # 検証
    assert text == "今日は晴れ"
