"""共通ユーティリティモジュール。"""

import csv
from pathlib import Path

from voice_paste.logger import get_logger

logger = get_logger(__name__)


def load_prompt(prompt_file: Path) -> str:
    """
    プロンプトファイル（用語集）を読み込む。

    :param prompt_file: プロンプトファイルのパス
    :return: プロンプト文字列（ファイルが存在しない場合は空文字）
    """
    if not prompt_file.exists():
        logger.warning("Prompt file not found: %s", prompt_file)
        return ""

    prompt = prompt_file.read_text(encoding="utf-8").strip()
    logger.info("Prompt loaded from %s (%d chars)", prompt_file, len(prompt))
    return prompt


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
    """用語集に基づいて文字起こし結果を単純置換する。

    Whisper への initial_prompt はヒントにすぎず採用されないことがあるため、
    確実に直したい語は後処理でも置換する。
    """
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


def build_initial_prompt(prompt: str, glossary: list[tuple[str, str]]) -> str:
    """
    プロンプトと用語集を結合してWhisperのinitial_promptを構築する。

    :param prompt: プロンプトファイルの内容
    :param glossary: (誤変換, 正しい表記) のリスト
    :return: 結合されたinitial_prompt文字列
    """
    parts: list[str] = []

    if prompt:
        parts.append(prompt)

    if glossary:
        lines = [
            f"「{wrong}」と聞こえたら「{correct}」と表記する"
            for wrong, correct in glossary
        ]
        parts.append(
            "次の用語は必ず指定の表記で出力してください。"
            "読み方が一致したら原則として右側の表記に統一します。\n"
            + "\n".join(lines)
        )

    result = "\n\n".join(parts)
    if result:
        logger.info("Initial prompt built: %d chars", len(result))
    return result
