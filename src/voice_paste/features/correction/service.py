"""用語集の読み込みと、誤変換の置き換え。"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from voice_paste.features.correction.types import GlossaryEntry

logger = logging.getLogger(__name__)

WRONG_COLUMN: str = "誤変換"
"""用語集の CSV の、誤変換の列の名前。"""

RIGHT_COLUMN: str = "正しい表記"
"""用語集の CSV の、正しい表記の列の名前。"""


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """用語集の CSV を読む。ファイルが無ければ空を返す。"""
    # 1. ファイルが無ければ空を返す
    if not path.exists():
        logger.warning(f"用語集が無い（{path}）")
        return []

    # 2. UTF-8（BOM ありも）の CSV を列名で読み、前後の空白を除く
    entries: list[GlossaryEntry] = []
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            wrong = (row.get(WRONG_COLUMN) or "").strip()
            right = (row.get(RIGHT_COLUMN) or "").strip()
            # どちらかが空の行は飛ばす
            if wrong and right:
                entries.append(GlossaryEntry(wrong=wrong, right=right))

    logger.info(f"用語集を読んだ（{path}・{len(entries)} 行）")
    return entries


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
