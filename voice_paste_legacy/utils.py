"""共通ユーティリティモジュール。"""

import csv
from pathlib import Path

from voice_paste.logger import get_logger

logger = get_logger(__name__)


def load_yogo(yogo_file: Path) -> list[tuple[str, str]]:
    """
    用語集CSVを読み込む。

    :param yogo_file: CSVファイルのパス（カラム: 誤変換, 正しい表記）
    :return: (誤変換, 正しい表記) のリスト
    """
    if not yogo_file.exists():
        logger.warning("Yogo file not found: %s", yogo_file)
        return []

    entries: list[tuple[str, str]] = []
    with open(yogo_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wrong = row.get("誤変換", "").strip()
            correct = row.get("正しい表記", "").strip()
            if wrong and correct:
                entries.append((wrong, correct))

    logger.info("Yogo loaded from %s (%d entries)", yogo_file, len(entries))
    return entries


def apply_yogo_replacements(text: str, glossary: list[tuple[str, str]]) -> str:
    """用語集に基づいて文字起こし結果を単純置換する。"""
    if not text or not glossary:
        return text
    result = text
    replaced: list[str] = []
    for wrong, correct in glossary:
        if wrong and wrong in result:
            result = result.replace(wrong, correct)
            replaced.append(f"{wrong}→{correct}")
    if replaced:
        logger.info("Yogo replacements applied: %s", ", ".join(replaced))
    return result
