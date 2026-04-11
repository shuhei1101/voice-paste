"""共通ユーティリティモジュール。"""

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
