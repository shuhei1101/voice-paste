"""録音・文字起こし履歴の保存と自動削除を管理するモジュール。"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from voice_paste import config
from voice_paste.constants import HISTORY_DIR
from voice_paste.logger import get_logger

logger = get_logger(__name__)


def save_history(audio_file: Path, text: str) -> None:
    """録音WAVと文字起こしテキストを履歴に保存する。

    :param audio_file: 録音WAVファイルのパス
    :param text: 文字起こし結果テキスト
    """
    if not config.HISTORY_ENABLED:
        return

    now = datetime.now()
    date_dir = HISTORY_DIR / now.strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%Y%m%d%H%M%S")

    # WAVファイルをコピー
    if audio_file.exists():
        wav_dest = date_dir / f"{timestamp}_recording.wav"
        shutil.copy2(audio_file, wav_dest)
        logger.info("History saved: %s", wav_dest)

    # テキストを保存
    if text:
        txt_dest = date_dir / f"{timestamp}_text.txt"
        txt_dest.write_text(text, encoding="utf-8")
        logger.info("History saved: %s", txt_dest)


def cleanup_history() -> None:
    """保持期間を過ぎた履歴フォルダを削除する。"""
    if not config.HISTORY_ENABLED:
        return

    if not HISTORY_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=config.HISTORY_RETENTION_DAYS)
    cutoff_str = cutoff.strftime("%Y%m%d")

    for entry in HISTORY_DIR.iterdir():
        if not entry.is_dir():
            continue
        # フォルダ名が YYYYMMDD 形式かチェック
        if len(entry.name) == 8 and entry.name.isdigit() and entry.name < cutoff_str:
            try:
                shutil.rmtree(entry)
                logger.info("History cleaned up: %s", entry)
            except Exception:
                logger.exception("Failed to clean up history: %s", entry)
