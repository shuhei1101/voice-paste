"""features/correction/service.py（load_glossary・apply_glossary・read_glossary_rows・save_glossary・resolve_glossaries・resolve_glossary_presets・pick_glossary_preset・list_preset_glossaries・next_glossary_path・strip_edge_phrases）の単体テスト。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from voice_paste.shared.settings import GlossarySettings, Settings

CSV_HEADER = "誤変換,正しい表記\n"
CSV_HEADER_WITH_ENABLED = "誤変換,正しい表記,使う\n"
OVER_FIELD_LIMIT_LENGTH = 200000
"""csv の 1 項目の上限（131072 文字）を超える長さ。"""


@pytest.fixture
def glossary_file(tmp_path: Path) -> Path:
    """一時フォルダの用語集の CSV のパスを返す（ファイルはまだ無い）。"""
    return tmp_path / "yogo.csv"


# === load_glossary ===


def test_load_glossary(glossary_file: Path) -> None:
    """CSV の行を読む（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.shared.types import GlossaryEntry

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
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER}くろーど,Claude\n", encoding="utf-8-sig")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == [GlossaryEntry(wrong="くろーど", right="Claude")]


def test_load_glossary_when_blank_cells(glossary_file: Path) -> None:
    """空白を除き、誤変換が空の行を飛ばし、正しい表記が空の行を残す（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER} くろーど , Claude \nあいう,\n,えお\n", encoding="utf-8")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == [
        GlossaryEntry(wrong="くろーど", right="Claude"),
        GlossaryEntry(wrong="あいう", right=""),
    ]


def test_load_glossary_when_disabled_rows(glossary_file: Path) -> None:
    """オフの行を飛ばす（正常系）。"""
    from voice_paste.features.correction.service import load_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備（列 `使う` が「1」「0」「（空）」の 3 行）
    glossary_file.write_text(f"{CSV_HEADER_WITH_ENABLED}あ,A,1\nい,B,0\nう,C,\n", encoding="utf-8")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証（「1」と「（空）」の 2 行だけが返る）
    assert entries == [
        GlossaryEntry(wrong="あ", right="A"),
        GlossaryEntry(wrong="う", right="C"),
    ]


def test_load_glossary_when_unreadable(glossary_file: Path) -> None:
    """読めない CSV は空として扱い、例外を上げない（正常系）。"""
    from voice_paste.features.correction.service import load_glossary

    # 準備（Shift_JIS で書いた 1 行の CSV）
    glossary_file.write_bytes(f"{CSV_HEADER}くろーど,Claude\n".encode("shift_jis"))

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == []


def test_load_glossary_when_malformed(glossary_file: Path) -> None:
    """csv が解釈できない CSV も空として扱い、例外を上げない（正常系）。"""
    from voice_paste.features.correction.service import load_glossary

    # 準備（見出しの次の行が「あ,"」で始まり、閉じない引用符の後ろに x を 200000 文字続けた CSV）
    glossary_file.write_text(f'{CSV_HEADER}あ,"' + "x" * OVER_FIELD_LIMIT_LENGTH, encoding="utf-8")

    # 実行
    entries = load_glossary(glossary_file)

    # 検証
    assert entries == []


# === apply_glossary ===


def test_apply_glossary() -> None:
    """誤変換を置き換える（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="くろーどこーど", right="Claude Code")]

    # 実行
    text = apply_glossary("今日はくろーどこーどを使う", entries)

    # 検証
    assert text == "今日はClaude Codeを使う"


def test_apply_glossary_when_chained() -> None:
    """前の行で置き換えた結果に次の行を当てる（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="A", right="B"), GlossaryEntry(wrong="B", right="C")]

    # 実行
    text = apply_glossary("A", entries)

    # 検証
    assert text == "C"


def test_apply_glossary_when_no_match() -> None:
    """誤変換を含まなければそのまま返す（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="くろーどこーど", right="Claude Code")]

    # 実行
    text = apply_glossary("今日は晴れ", entries)

    # 検証
    assert text == "今日は晴れ"


def test_apply_glossary_when_right_empty() -> None:
    """正しい表記が空の行は誤変換を消す（正常系）。"""
    from voice_paste.features.correction.service import apply_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    entries = [GlossaryEntry(wrong="ご視聴ありがとうございました", right="")]

    # 実行
    text = apply_glossary("今日はここまで。ご視聴ありがとうございました", entries)

    # 検証
    assert text == "今日はここまで。"


# === read_glossary_rows ===


def test_read_glossary_rows(glossary_file: Path) -> None:
    """行をオン・オフつきで読む（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER_WITH_ENABLED}あ,A,1\nい,B,0\n", encoding="utf-8")

    # 実行
    rows = read_glossary_rows(glossary_file)

    # 検証
    assert rows == [
        GlossaryEntry(wrong="あ", right="A", enabled=True),
        GlossaryEntry(wrong="い", right="B", enabled=False),
    ]


def test_read_glossary_rows_when_no_enabled_column(glossary_file: Path) -> None:
    """列 `使う` が無い CSV の行は全てオン（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER}あ,A\nい,B\n", encoding="utf-8")

    # 実行
    rows = read_glossary_rows(glossary_file)

    # 検証
    assert rows == [
        GlossaryEntry(wrong="あ", right="A", enabled=True),
        GlossaryEntry(wrong="い", right="B", enabled=True),
    ]


def test_read_glossary_rows_when_half_empty(glossary_file: Path) -> None:
    """片方が空の行は返し、両方が空の行は飛ばす（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.types import GlossaryEntry

    # 準備
    glossary_file.write_text(f"{CSV_HEADER}あいう,\n,えお\n,\n", encoding="utf-8")

    # 実行
    rows = read_glossary_rows(glossary_file)

    # 検証
    assert rows == [
        GlossaryEntry(wrong="あいう", right=""),
        GlossaryEntry(wrong="", right="えお"),
    ]


def test_read_glossary_rows_when_missing(tmp_path: Path) -> None:
    """ファイルが無ければ空（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows

    # 実行
    rows = read_glossary_rows(tmp_path / "missing.csv")

    # 検証
    assert rows == []


def test_read_glossary_rows_when_not_utf8(glossary_file: Path) -> None:
    """UTF-8 でない CSV は読めないとする（異常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.errors import GlossaryReadError

    # 準備（Shift_JIS で書いた 1 行の CSV）
    glossary_file.write_bytes(f"{CSV_HEADER}くろーど,Claude\n".encode("shift_jis"))

    # 実行・検証
    with pytest.raises(GlossaryReadError, match="文字コードが UTF-8 ではありません"):
        read_glossary_rows(glossary_file)


def test_read_glossary_rows_when_no_header(glossary_file: Path) -> None:
    """見出しの列が無い CSV は読めないとする（異常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.errors import GlossaryReadError

    # 準備（1 行目が「くろーど,Claude」で、見出しの無い CSV）
    glossary_file.write_text("くろーど,Claude\nあ,A\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(GlossaryReadError, match="見出しに「誤変換」「正しい表記」の列がありません"):
        read_glossary_rows(glossary_file)


def test_read_glossary_rows_when_unreadable(tmp_path: Path) -> None:
    """開けない CSV は読めないとする（異常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.errors import GlossaryReadError

    # 準備（path にフォルダを渡す）
    folder = tmp_path / "folder.csv"
    folder.mkdir()

    # 実行・検証
    with pytest.raises(GlossaryReadError, match="^ファイルを開けません（"):
        read_glossary_rows(folder)


def test_read_glossary_rows_when_malformed(glossary_file: Path) -> None:
    """csv が解釈できない CSV は読めないとする（異常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows
    from voice_paste.shared.errors import GlossaryReadError

    # 準備（見出しの次の行が「あ,"」で始まり、閉じない引用符の後ろに x を 200000 文字続けた CSV）
    glossary_file.write_text(f'{CSV_HEADER}あ,"' + "x" * OVER_FIELD_LIMIT_LENGTH, encoding="utf-8")

    # 実行・検証
    with pytest.raises(GlossaryReadError, match="^CSV の書式が正しくありません（"):
        read_glossary_rows(glossary_file)


# === save_glossary ===


def test_save_glossary(glossary_file: Path) -> None:
    """書いた行を同じ順とオン・オフで読み戻せる（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows, save_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備（オンとオフの 2 行）
    written = [
        GlossaryEntry(wrong="あ", right="A", enabled=True),
        GlossaryEntry(wrong="い", right="B", enabled=False),
    ]

    # 実行
    save_glossary(glossary_file, written)

    # 検証
    assert read_glossary_rows(glossary_file) == written


def test_save_glossary_when_new_directory(tmp_path: Path) -> None:
    """親のフォルダが無ければ作る（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows, save_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備（存在しないフォルダの下のパス）
    path = tmp_path / "not_created" / "glossaries" / "glossary_1.csv"

    # 実行
    save_glossary(path, [GlossaryEntry(wrong="あ", right="A")])

    # 検証
    assert path.exists()
    assert read_glossary_rows(path) == [GlossaryEntry(wrong="あ", right="A")]


def test_save_glossary_when_both_empty_row(glossary_file: Path) -> None:
    """両方が空の行は書かない（正常系）。"""
    from voice_paste.features.correction.service import read_glossary_rows, save_glossary
    from voice_paste.shared.types import GlossaryEntry

    # 準備（誤変換と正しい表記が空の行を 1 つ含む 2 行）
    entries = [GlossaryEntry(wrong="あ", right="A"), GlossaryEntry(wrong="", right="")]

    # 実行
    save_glossary(glossary_file, entries)

    # 検証
    assert read_glossary_rows(glossary_file) == [GlossaryEntry(wrong="あ", right="A")]


# === resolve_glossaries ===


def test_resolve_glossaries_when_empty(tmp_path: Path, settings_model: type[Settings]) -> None:
    """一覧が空でキーも無ければ、設定のフォルダの yogo.csv が 1 件目（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossaries
    from voice_paste.shared.settings import GlossarySettings

    # 準備
    settings_dir = tmp_path / "settings"

    # 実行
    glossaries = resolve_glossaries(settings_model(), settings_dir)

    # 検証
    assert glossaries == [GlossarySettings(name="yogo", path=settings_dir / "yogo.csv")]


def test_resolve_glossaries_when_legacy_path(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """一覧が空で glossary_path があれば、その CSV が 1 件目（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossaries
    from voice_paste.shared.settings import GlossarySettings

    # 準備
    legacy_path = tmp_path / "elsewhere" / "terms.csv"
    settings = settings_model(glossary_path=legacy_path)

    # 実行
    glossaries = resolve_glossaries(settings, tmp_path / "settings")

    # 検証
    assert glossaries == [GlossarySettings(name="terms", path=legacy_path)]


def test_resolve_glossaries_when_relative_path(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """相対パスを設定のフォルダから解決し、絶対パスはそのまま返す（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossaries
    from voice_paste.shared.settings import GlossarySettings

    # 準備（path が `glossaries/glossary_1.csv` と絶対パスの 2 件）
    settings_dir = tmp_path / "settings"
    absolute_path = tmp_path / "elsewhere" / "terms.csv"
    settings = settings_model(
        glossaries=[
            GlossarySettings(name="会議用", path=Path("glossaries/glossary_1.csv")),
            GlossarySettings(name="雑談用", path=absolute_path),
        ]
    )

    # 実行
    glossaries = resolve_glossaries(settings, settings_dir)

    # 検証（1 件目は settings_dir の下の絶対パス、2 件目は元のまま。並びと名前は変わらない）
    assert glossaries == [
        GlossarySettings(name="会議用", path=settings_dir / "glossaries" / "glossary_1.csv"),
        GlossarySettings(name="雑談用", path=absolute_path),
    ]


def test_resolve_glossaries_when_relative_legacy_path(
    tmp_path: Path, settings_model: type[Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """相対パスの glossary_path は、起動したフォルダからの絶対パスにする（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossaries

    # 準備（settings_dir とは別のフォルダを、起動したフォルダにする）
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    settings = settings_model(glossary_path=Path("terms.csv"))

    # 実行
    glossaries = resolve_glossaries(settings, tmp_path / "settings")

    # 検証（settings_dir の下ではなく、起動したフォルダの terms.csv の絶対パス）
    assert len(glossaries) == 1
    assert glossaries[0].path == Path.cwd() / "terms.csv"


# === resolve_glossary_presets ===


def _two_glossaries(settings_dir: Path) -> list[GlossarySettings]:
    """「yogo」「会議用」の 2 件の用語集を作る。"""
    from voice_paste.shared.settings import GlossarySettings

    return [
        GlossarySettings(name="yogo", path=settings_dir / "yogo.csv"),
        GlossarySettings(name="会議用", path=settings_dir / "meeting.csv"),
    ]


def test_resolve_glossary_presets_when_empty(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """プリセットのキーが無く active_glossary も無ければ、1 つ目の用語集だけの「既定」（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossary_presets
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    settings = settings_model(glossaries=_two_glossaries(tmp_path), active_glossary=None)

    # 実行
    presets = resolve_glossary_presets(settings, tmp_path)

    # 検証
    assert presets == [GlossaryPresetSettings(name="既定", glossaries=["yogo"])]


def test_resolve_glossary_presets_when_legacy_active(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """プリセットのキーが無ければ、active_glossary の用語集だけの「既定」（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossary_presets
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    settings = settings_model(glossaries=_two_glossaries(tmp_path), active_glossary="会議用")

    # 実行
    presets = resolve_glossary_presets(settings, tmp_path)

    # 検証
    assert presets == [GlossaryPresetSettings(name="既定", glossaries=["会議用"])]


def test_resolve_glossary_presets_when_legacy_unknown_active(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """active_glossary が一覧に無ければ、1 つ目の用語集だけの「既定」（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossary_presets
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    settings = settings_model(
        glossaries=_two_glossaries(tmp_path), active_glossary="存在しない名前"
    )

    # 実行
    presets = resolve_glossary_presets(settings, tmp_path)

    # 検証
    assert presets == [GlossaryPresetSettings(name="既定", glossaries=["yogo"])]


def test_resolve_glossary_presets(tmp_path: Path, settings_model: type[Settings]) -> None:
    """プリセットの並びと中の用語集の並びをそのまま返し、一覧に無い名前を外す（正常系）。"""
    from voice_paste.features.correction.service import resolve_glossary_presets
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    settings = settings_model(
        glossaries=_two_glossaries(tmp_path),
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
            GlossaryPresetSettings(name="会議", glossaries=["会議用", "消した", "yogo"]),
        ],
    )

    # 実行
    presets = resolve_glossary_presets(settings, tmp_path)

    # 検証
    assert presets == [
        GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
        GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"]),
    ]


# === pick_glossary_preset ===


def _settings_with_presets(
    settings_model: type[Settings], settings_dir: Path, active_glossary_preset: str | None
) -> Settings:
    """「既定」「会議」の 2 件の glossary_presets と active_glossary_preset を持つ設定を作る。"""
    from voice_paste.shared.settings import GlossaryPresetSettings

    return settings_model(
        glossaries=_two_glossaries(settings_dir),
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
            GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"]),
        ],
        active_glossary_preset=active_glossary_preset,
    )


def test_pick_glossary_preset(tmp_path: Path, settings_model: type[Settings]) -> None:
    """active_glossary_preset の名前のプリセットを返す（正常系）。"""
    from voice_paste.features.correction.service import pick_glossary_preset
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    settings = _settings_with_presets(settings_model, tmp_path, "会議")

    # 実行
    preset = pick_glossary_preset(settings, tmp_path)

    # 検証
    assert preset == GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"])


def test_pick_glossary_preset_when_unset(tmp_path: Path, settings_model: type[Settings]) -> None:
    """active_glossary_preset が無ければ 1 件目（正常系）。"""
    from voice_paste.features.correction.service import pick_glossary_preset

    # 準備
    settings = _settings_with_presets(settings_model, tmp_path, None)

    # 実行
    preset = pick_glossary_preset(settings, tmp_path)

    # 検証
    assert preset.name == "既定"


def test_pick_glossary_preset_when_unknown_name(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """一覧に無い名前なら 1 件目（正常系）。"""
    from voice_paste.features.correction.service import pick_glossary_preset

    # 準備
    settings = _settings_with_presets(settings_model, tmp_path, "存在しない名前")

    # 実行
    preset = pick_glossary_preset(settings, tmp_path)

    # 検証
    assert preset.name == "既定"


def test_pick_glossary_preset_when_requested(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """指定した名前があれば、設定で選んでいるプリセットより優先する（正常系）。"""
    from voice_paste.features.correction.service import pick_glossary_preset

    # 準備（active_glossary_preset = 既定、requested = 会議）
    settings = _settings_with_presets(settings_model, tmp_path, "既定")

    # 実行
    preset = pick_glossary_preset(settings, tmp_path, requested="会議")

    # 検証
    assert preset.name == "会議"


def test_pick_glossary_preset_when_requested_missing(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """指定した名前が一覧に無ければ、設定で選んでいるプリセットを返す（正常系）。"""
    from voice_paste.features.correction.service import pick_glossary_preset

    # 準備（active_glossary_preset = 会議、requested = 消したプリセット）
    settings = _settings_with_presets(settings_model, tmp_path, "会議")

    # 実行
    preset = pick_glossary_preset(settings, tmp_path, requested="消したプリセット")

    # 検証
    assert preset.name == "会議"


# === list_preset_glossaries ===


def test_list_preset_glossaries(tmp_path: Path) -> None:
    """プリセットに並べた順で返す（用語集の一覧の順ではない）（正常系）。"""
    from voice_paste.features.correction.service import list_preset_glossaries
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings

    # 準備（一覧が「yogo」「会議用」の順で、プリセットは ["会議用", "yogo"]）
    preset = GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"])

    # 実行
    glossaries = list_preset_glossaries(preset, _two_glossaries(tmp_path))

    # 検証
    assert glossaries == [
        GlossarySettings(name="会議用", path=tmp_path / "meeting.csv"),
        GlossarySettings(name="yogo", path=tmp_path / "yogo.csv"),
    ]


def test_list_preset_glossaries_when_empty(tmp_path: Path) -> None:
    """使う用語集が無いプリセットは空を返す（正常系）。"""
    from voice_paste.features.correction.service import list_preset_glossaries
    from voice_paste.shared.settings import GlossaryPresetSettings

    # 準備
    preset = GlossaryPresetSettings(name="空", glossaries=[])

    # 実行
    glossaries = list_preset_glossaries(preset, _two_glossaries(tmp_path))

    # 検証
    assert glossaries == []


# === next_glossary_path ===


def test_next_glossary_path(tmp_path: Path) -> None:
    """空のフォルダなら 1 番（正常系）。"""
    from voice_paste.features.correction.service import next_glossary_path

    # 準備（存在しない directory と空の taken）
    directory = tmp_path / "glossaries"

    # 実行
    path = next_glossary_path([], directory=directory)

    # 検証
    assert path == directory / "glossary_1.csv"


def test_next_glossary_path_when_file_exists(tmp_path: Path) -> None:
    """残っている CSV の番号は使わない（正常系）。"""
    from voice_paste.features.correction.service import next_glossary_path

    # 準備（glossary_1.csv がある directory と空の taken）
    directory = tmp_path / "glossaries"
    directory.mkdir()
    (directory / "glossary_1.csv").write_text(CSV_HEADER, encoding="utf-8")

    # 実行
    path = next_glossary_path([], directory=directory)

    # 検証
    assert path == directory / "glossary_2.csv"


def test_next_glossary_path_when_taken(tmp_path: Path) -> None:
    """保存する前に足した用語集の場所とも重ねない（正常系）。"""
    from voice_paste.features.correction.service import next_glossary_path

    # 準備（空の directory と、glossary_1.csv を含む taken）
    directory = tmp_path / "glossaries"
    taken = [directory / "glossary_1.csv"]

    # 実行
    path = next_glossary_path(taken, directory=directory)

    # 検証
    assert path == directory / "glossary_2.csv"


# === strip_edge_phrases ===


def test_strip_edge_phrases() -> None:
    """一覧の順に文末から消し、文頭の行は文頭だけに当てる（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（上から「チャンネル登録*」「ご視聴ありがとうございました」「ありがとうございました」が文末、「えーと」が文頭）
    phrases = [
        EdgePhraseSettings(text="チャンネル登録*", position="end"),
        EdgePhraseSettings(text="ご視聴ありがとうございました", position="end"),
        EdgePhraseSettings(text="ありがとうございました", position="end"),
        EdgePhraseSettings(text="えーと", position="start"),
    ]
    text = (
        "えーと、ありがとうございました。本日の議題は予算です。\n"
        "以上です。ありがとうございました。ご視聴ありがとうございました。"
        "チャンネル登録よろしくお願いします。"
    )

    # 実行
    result = strip_edge_phrases(text, phrases)

    # 検証
    assert result == "ありがとうございました。本日の議題は予算です。\n以上です。"


def test_strip_edge_phrases_when_middle() -> None:
    """文頭・文末以外の同じ文言は消さない（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「ありがとうございました」（両方）の 1 行）
    phrases = [EdgePhraseSettings(text="ありがとうございました", position="both")]

    # 実行
    result = strip_edge_phrases("先日はありがとうございましたと伝えた。", phrases)

    # 検証
    assert result == "先日はありがとうございましたと伝えた。"


def test_strip_edge_phrases_when_wildcard_start() -> None:
    """文頭の末尾の `*` は 1 行目の行末まで消す（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「字幕*」（文頭）の 1 行）
    phrases = [EdgePhraseSettings(text="字幕*", position="start")]

    # 実行
    result = strip_edge_phrases("字幕：山田\n本題です。", phrases)

    # 検証
    assert result == "本題です。"


def test_strip_edge_phrases_when_wildcard_middle() -> None:
    """途中の `*` は消す文字が最も短い一致を使う（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「ご*した」（文末）の 1 行）
    phrases = [EdgePhraseSettings(text="ご*した", position="end")]

    # 実行
    result = strip_edge_phrases("ご飯を食べた。ご視聴に感謝した", phrases)

    # 検証
    assert result == "ご飯を食べた。"


def test_strip_edge_phrases_when_repeated() -> None:
    """同じ文言が端に続けて並ぶときは続く分も消す（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「ご視聴ありがとうございました」（文末）の 1 行）
    phrases = [EdgePhraseSettings(text="ご視聴ありがとうございました", position="end")]

    # 実行
    result = strip_edge_phrases(
        "以上です。ご視聴ありがとうございました。ご視聴ありがとうございました", phrases
    )

    # 検証
    assert result == "以上です。"


def test_strip_edge_phrases_when_line_emptied() -> None:
    """最後の行が空になったら前の行で続ける（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「ご視聴ありがとうございました」「ありがとうございました」（どちらも文末）の 2 行）
    phrases = [
        EdgePhraseSettings(text="ご視聴ありがとうございました", position="end"),
        EdgePhraseSettings(text="ありがとうございました", position="end"),
    ]

    # 実行
    result = strip_edge_phrases("本題です。ありがとうございました。\nご視聴ありがとうございました。", phrases)

    # 検証
    assert result == "本題です。"


def test_strip_edge_phrases_when_all_removed() -> None:
    """全て消えたら空文字を返す（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases
    from voice_paste.shared.settings import EdgePhraseSettings

    # 準備（「ご視聴ありがとうございました」（文末）の 1 行）
    phrases = [EdgePhraseSettings(text="ご視聴ありがとうございました", position="end")]

    # 実行
    result = strip_edge_phrases("ご視聴ありがとうございました。", phrases)

    # 検証
    assert result == ""


def test_strip_edge_phrases_when_empty_list() -> None:
    """一覧が空ならそのまま返す（正常系）。"""
    from voice_paste.features.correction.service import strip_edge_phrases

    # 実行（空の一覧）
    result = strip_edge_phrases("ご視聴ありがとうございました", [])

    # 検証
    assert result == "ご視聴ありがとうございました"
