"""用語集の一覧の解決、CSV の読み書き、誤変換の置き換え。"""

from __future__ import annotations

import csv
import logging
import os
import re
import tempfile
from collections.abc import Collection, Sequence
from pathlib import Path

from voice_paste.shared.errors import GlossaryReadError
from voice_paste.shared.settings import (
    EDGE_PHRASE_WILDCARD,
    EdgePhraseSettings,
    GlossaryPresetSettings,
    GlossarySettings,
    Settings,
)
from voice_paste.shared.types import GlossaryEntry

logger = logging.getLogger(__name__)

WRONG_COLUMN: str = "誤変換"
"""用語集の CSV の、誤変換の列の名前。"""

RIGHT_COLUMN: str = "正しい表記"
"""用語集の CSV の、正しい表記の列の名前。"""

ENABLED_COLUMN: str = "使う"
"""用語集の CSV の、行を補正に使うかの列の名前。"""

ENABLED_VALUE: str = "1"
"""列 `使う` で、オンを書く値。"""

DISABLED_VALUE: str = "0"
"""列 `使う` で、オフの値（列が無い・空・ほかの値はオン）。"""

DEFAULT_GLOSSARY_FILE_NAME: str = "yogo.csv"
"""`glossaries` も `glossary_path` も無いときに読む、settings.toml と同じフォルダの用語集のファイル名。"""

DEFAULT_GLOSSARY_PRESET_NAME: str = "既定"
"""`glossary_presets` のキーが無い・空の settings.toml で、resolve_glossary_presets が作る 1 つだけのプリセットの名前。"""

GLOSSARY_FILE_PATTERN: str = "glossary_{number}.csv"
"""設定画面で足した用語集の CSV のファイル名。number は 1 からの連番。"""

DELETED_MARK: str = "（消す）"
"""正しい表記が空の行で誤変換を消したことを、置き換えのログの「→」の右に出す表示。"""

EDGE_TRAILING_CHARS: str = "。、，．,.!?！？ 　\t"
"""一致した文言の後ろに続くとき、文言と一緒に消す句読点と空白。"""

EDGE_START_LABEL: str = "文頭"
"""文頭から消したことを、消した文言のログに出す表示。"""

EDGE_END_LABEL: str = "文末"
"""文末から消したことを、消した文言のログに出す表示。"""


def read_glossary_rows(path: Path) -> list[GlossaryEntry]:
    """用語集の CSV の行を、オン・オフと片方が空の行も含めて読む。ファイルが無ければ空を返す。

    開けない・UTF-8 でない・見出しの列が無い・csv が解釈できない CSV は、理由を持つ GlossaryReadError にする。
    """
    # 1. ファイルが無ければ空を返す
    if not path.exists():
        logger.warning(f"用語集が無い（{path}）")
        return []

    # 2. UTF-8（BOM ありも）の CSV を列名で読み、前後の空白を除く
    rows: list[GlossaryEntry] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            # 見出しに誤変換と正しい表記の列が無ければ読めない
            if not {WRONG_COLUMN, RIGHT_COLUMN} <= set(reader.fieldnames or []):
                raise GlossaryReadError("見出しに「誤変換」「正しい表記」の列がありません")
            for row in reader:
                wrong = (row.get(WRONG_COLUMN) or "").strip()
                right = (row.get(RIGHT_COLUMN) or "").strip()
                # 両方が空の行は飛ばす（片方だけが空の行は返す）
                if not wrong and not right:
                    continue
                # 3. 列 `使う` の値が 0 の行だけをオフにする
                enabled = (row.get(ENABLED_COLUMN) or "").strip() != DISABLED_VALUE
                rows.append(GlossaryEntry(wrong=wrong, right=right, enabled=enabled))
    except OSError as error:
        raise GlossaryReadError(f"ファイルを開けません（{error}）") from error
    except UnicodeDecodeError as error:
        raise GlossaryReadError("文字コードが UTF-8 ではありません") from error
    except csv.Error as error:
        raise GlossaryReadError(f"CSV の書式が正しくありません（{error}）") from error
    return rows


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """用語集の CSV から、補正に使う行（オンで、誤変換がある行。正しい表記が空の行は誤変換を消す行）を読む。読めなければ空を返す。"""
    # 1. 行を読む（読めない CSV は補正せずに届けるため、空にする）
    try:
        rows = read_glossary_rows(path)
    except GlossaryReadError as error:
        logger.warning(f"用語集を読めなかった（{path}: {error}）")
        return []

    # 2. オフの行と、誤変換が空の行を飛ばす（正しい表記が空の行は、誤変換を消す行として残す）
    entries = [row for row in rows if row.enabled and row.wrong]
    logger.info(f"用語集を読んだ（{path}・{len(rows)} 行・補正に使う {len(entries)} 行）")
    return entries


def save_glossary(path: Path, entries: Sequence[GlossaryEntry]) -> None:
    """用語集の行を CSV へ書く。親のフォルダが無ければ作り、書けなければ元の CSV を変えずに OSError にする。"""
    # 1. 親のフォルダを作る
    path.parent.mkdir(parents=True, exist_ok=True)

    # 2. 同じフォルダの一時ファイルに、UTF-8（BOM あり）で見出しと行を書く（両方が空の行は書かない）
    written = [entry for entry in entries if entry.wrong or entry.right]
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        writer = csv.writer(temp_file)
        writer.writerow([WRONG_COLUMN, RIGHT_COLUMN, ENABLED_COLUMN])
        for entry in written:
            writer.writerow(
                [entry.wrong, entry.right, ENABLED_VALUE if entry.enabled else DISABLED_VALUE]
            )
        temp_path = Path(temp_file.name)

    # 3. 置き換える（置き換えられなければ一時ファイルを消す）
    try:
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
    logger.info(f"用語集を書いた（{path}・{len(written)} 行）")


def resolve_glossaries(settings: Settings, settings_dir: Path) -> list[GlossarySettings]:
    """設定から、CSV の場所を絶対パスにした用語集の一覧を返す。glossaries が空なら、今までの glossary_path の CSV を 1 つ目にする。"""
    # 1. glossaries が空なら、今までの用語集の CSV を 1 つ目の用語集にする
    if not settings.glossaries:
        # 相対パスの glossary_path は、今までと同じく起動したフォルダからの絶対パスにする
        legacy_path = (settings.glossary_path or settings_dir / DEFAULT_GLOSSARY_FILE_NAME).absolute()
        return [GlossarySettings(name=legacy_path.stem, path=legacy_path)]

    # 2. glossaries の並びのまま、相対パスを settings_dir からのパスにする
    return [
        GlossarySettings(
            name=glossary.name,
            path=glossary.path if glossary.path.is_absolute() else settings_dir / glossary.path,
        )
        for glossary in settings.glossaries
    ]


def resolve_glossary_presets(settings: Settings, settings_dir: Path) -> list[GlossaryPresetSettings]:
    """設定から用語集のプリセットの一覧を返す。glossary_presets が空なら、active_glossary の用語集だけを使う「既定」のプリセット 1 件にする。用語集の一覧に無い名前はプリセットから外す。"""
    # 1. 用語集の一覧を引き、名前の並びにする
    names = [glossary.name for glossary in resolve_glossaries(settings, settings_dir)]

    # 2. glossary_presets が空なら、active_glossary（無い・一覧に無ければ 1 つ目）の用語集だけを使う「既定」の 1 件にする
    if not settings.glossary_presets:
        legacy_name = settings.active_glossary if settings.active_glossary in names else names[0]
        return [GlossaryPresetSettings(name=DEFAULT_GLOSSARY_PRESET_NAME, glossaries=[legacy_name])]

    # 3. glossary_presets の並びのまま、各プリセットの用語集から一覧に無い名前を外す
    presets: list[GlossaryPresetSettings] = []
    for preset in settings.glossary_presets:
        kept = [name for name in preset.glossaries if name in names]
        removed = [name for name in preset.glossaries if name not in names]
        if removed:
            logger.warning(
                f"用語集の一覧に無い名前をプリセットから外した（{preset.name}・{'、'.join(removed)}）"
            )
        presets.append(GlossaryPresetSettings(name=preset.name, glossaries=kept))
    return presets


def pick_glossary_preset(
    settings: Settings, settings_dir: Path, *, requested: str | None = None
) -> GlossaryPresetSettings:
    """用語集のプリセットの一覧から、補正に使うプリセットを返す。指定した名前があればそれ、無ければ active_glossary_preset、それも無い・一覧に無いときは 1 件目を返す。"""
    presets = resolve_glossary_presets(settings, settings_dir)

    # 指定した名前が一覧にあればそのプリセットを返す
    if requested is not None:
        found = next((preset for preset in presets if preset.name == requested), None)
        if found is not None:
            return found
        # 開始の後に設定でそのプリセットを消した: 設定で選んでいるプリセットで補正する
        logger.warning(
            f"指定された用語集のプリセットが無いため、設定で選んでいるプリセットで補正する（{requested}）"
        )

    return next(
        (preset for preset in presets if preset.name == settings.active_glossary_preset),
        presets[0],
    )


def list_preset_glossaries(
    preset: GlossaryPresetSettings, glossaries: Sequence[GlossarySettings]
) -> list[GlossarySettings]:
    """用語集のプリセットが使う用語集を、プリセットに並べた順で返す。一覧に無い名前は飛ばす。"""
    by_name = {glossary.name: glossary for glossary in glossaries}
    return [by_name[name] for name in preset.glossaries if name in by_name]


def next_glossary_path(taken: Collection[Path], *, directory: Path) -> Path:
    """設定画面で足す用語集の CSV の場所を、今あるファイルとも一覧の用語集とも重ならない連番で決める。ファイルは作らない。"""
    number = 1
    while True:
        candidate = directory.absolute() / GLOSSARY_FILE_PATTERN.format(number=number)
        # directory に無く、一覧にも無い最初の番号を使う（消した用語集の CSV が残っていれば、その番号は使わない）
        if not candidate.exists() and candidate not in taken:
            return candidate
        number += 1


def apply_glossary(text: str, entries: list[GlossaryEntry]) -> str:
    """用語集の行の順に、前の行で置き換えた結果へ次の行を当てて誤変換を置き換える（正しい表記が空の行は誤変換を消す）。"""
    result = text
    replaced: list[str] = []
    for entry in entries:
        # 誤変換を含むなら全て正しい表記へ置き換える（正しい表記が空なら誤変換が消える）
        if entry.wrong in result:
            result = result.replace(entry.wrong, entry.right)
            replaced.append(f"{entry.wrong}→{entry.right or DELETED_MARK}")

    if replaced:
        logger.info(f"用語集で置き換えた（{', '.join(replaced)}）")
    return result


def _compile_edge_phrase(text: str) -> re.Pattern[str]:
    """文言を正規表現にする。`*` は改行をまたがない任意の文字列で、末尾の `*` は行の末尾まで、それ以外は最も短い一致にする。後ろに続く EDGE_TRAILING_CHARS は一緒に一致させる。"""
    parts = text.split(EDGE_PHRASE_WILDCARD)
    source = ""
    for index, part in enumerate(parts):
        source += re.escape(part)
        # 最後の部分の後ろには `*` が無い
        if index == len(parts) - 1:
            continue
        # 末尾の `*`（その後ろの部分が空）は行の末尾まで、途中・先頭の `*` は最短にする
        is_trailing = index == len(parts) - 2 and not parts[-1]
        source += ".*" if is_trailing else ".*?"
    return re.compile(f"{source}[{re.escape(EDGE_TRAILING_CHARS)}]*")


def _strip_start(lines: list[str], pattern: re.Pattern[str], removed: list[str]) -> None:
    """1 行目の先頭に文言が一致する間、一致した文字を消す。1 行目が空になったらその行を除いて次の行で続ける。"""
    while lines:
        matched = pattern.match(lines[0])
        # 一致しないか、何も消さない一致なら終える
        if matched is None or matched.end() == 0:
            return
        removed.append(f"{EDGE_START_LABEL}: {matched.group()}")
        lines[0] = lines[0][matched.end() :]
        # 1 行目が空になったら、その行を除く
        if not lines[0]:
            lines.pop(0)


def _strip_end(
    lines: list[str], pattern: re.Pattern[str], removed: list[str], *, from_line_start: bool
) -> None:
    """最後の行の末尾に文言が一致する間、一致した文字を消す。最後の行が空になったらその行を除いて前の行で続ける。"""
    while lines:
        line = lines[-1]
        # 先頭が `*` の文言は行の先頭から、それ以外は最も後ろから始まる一致を探す
        starts = [0] if from_line_start else range(len(line) - 1, -1, -1)
        start = next((index for index in starts if pattern.fullmatch(line, index)), None)
        if start is None:
            return
        removed.append(f"{EDGE_END_LABEL}: {line[start:]}")
        # 消した後の行の末尾の空白も除く
        lines[-1] = line[:start].rstrip()
        # 最後の行が空になったら、その行を除く
        if not lines[-1]:
            lines.pop()


def strip_edge_phrases(text: str, phrases: Sequence[EdgePhraseSettings]) -> str:
    """一覧の行を上から順に、前の行で消した結果へ当て、起こした文字の文頭・文末に一致した文言だけを消す。全て消えたら空文字を返す。"""
    # 1. 文字を改行で行に分ける
    lines = text.split("\n")
    removed: list[str] = []

    # 2. 一覧の行を上から順に当てる（文言が空の行は飛ばす）
    for phrase in phrases:
        if not phrase.text:
            continue
        pattern = _compile_edge_phrase(phrase.text)
        # 位置が文頭か両方なら、1 行目の先頭から消す
        if phrase.position in ("start", "both"):
            _strip_start(lines, pattern, removed)
        # 位置が文末か両方なら、最後の行の末尾から消す
        if phrase.position in ("end", "both"):
            _strip_end(
                lines,
                pattern,
                removed,
                from_line_start=phrase.text.startswith(EDGE_PHRASE_WILDCARD),
            )

    # 3. 消したものがあればログに残し、行をつないで返す
    if removed:
        logger.info(f"文頭・文末の文言を消した（{', '.join(removed)}）")
    return "\n".join(lines)
