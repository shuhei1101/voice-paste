"""ロガー初期化・設定集約モジュール。"""

import logging
import sys
from pathlib import Path

from voice_paste.constants import LOG_DIR


def setup_logger(log_level: str = "INFO") -> logging.Logger:
    """
    アプリケーション全体のロガーを初期化する。

    :param log_level: ログレベル文字列（DEBUG / INFO / WARNING / ERROR）
    :return: 初期化済みロガー
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)

    logger = logging.getLogger("voice_paste")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # ファイルハンドラ
    log_file = LOG_DIR / "voice_paste.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    logger.info("Logger initialized. level=%s, log_file=%s", log_level, log_file)
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    サブモジュール用のロガーを取得する。

    :param name: モジュール名（例: voice_paste.audio）
    :return: ロガー
    """
    return logging.getLogger(name)
