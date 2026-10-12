"""用語集の一覧の解決、CSV の読み書き、誤変換の置き換え。"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from collections.abc import Collection, Sequence
from pathlib import Path

from voice_paste.shared.errors import GlossaryReadError
from voice_paste.shared.settings import GlossarySettings, Settings
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

GLOSSARY_FILE_PATTERN: str = "glossary_{number}.csv"
"""設定画面で足した用語集の CSV のファイル名。number は 1 からの連番。"""


def read_glossary_rows(path: Path) -> list[GlossaryEntry]:
    """用語集の CSV の行を、オン・オフと片方が空の行も含めて読む。ファイルが無ければ空を返す。

    開けない・UTF-8 でない・見出しの列が無い CSV は、理由を持つ GlossaryReadError にする。
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
    return rows


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """用語集の CSV から、補正に使う行（オンで、誤変換と正しい表記の両方がある行）を読む。読めなければ空を返す。"""
    # 1. 行を読む（読めない CSV は補正せずに届けるため、空にする）
    try:
        rows = read_glossary_rows(path)
    except GlossaryReadError as error:
        logger.warning(f"用語集を読めなかった（{path}: {error}）")
        return []

    # 2. オフの行と、誤変換か正しい表記のどちらかが空の行を飛ばす
    entries = [row for row in rows if row.enabled and row.wrong and row.right]
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


def pick_active_glossary(settings: Settings, settings_dir: Path) -> GlossarySettings:
    """用語集の一覧から、active_glossary の名前の用語集を返す。名前が無い・一覧に無いときは 1 件目を返す。"""
    glossaries = resolve_glossaries(settings, settings_dir)
    return next(
        (glossary for glossary in glossaries if glossary.name == settings.active_glossary),
        glossaries[0],
    )


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
    """用語集の行の順に、前の行で置き換えた結果へ次の行を当てて誤変換を置き換える。"""
    result = text
    replaced: list[str] = []
    for entry in entries:
        # 誤変換を含むなら全て正しい表記へ置き換える
        if entry.wrong in result:
            result = result.replace(entry.wrong, entry.right)
            replaced.append(f"{entry.wrong}→{entry.right}")

    if replaced:
        logger.info(f"用語集で置き換えた（{', '.join(replaced)}）")
    return result
