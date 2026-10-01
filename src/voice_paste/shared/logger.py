"""標準の logging の設定。日付ごとのファイルへ JSON Lines で書き、保持期間を過ぎたログを消す。"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import IO, Literal

logger = logging.getLogger(__name__)

LOG_FILE_SUFFIX: str = ".log"
"""日付ごとのログのファイルの拡張子。"""

LOG_FILE_NAME_PATTERN: re.Pattern[str] = re.compile(r"\d{4}-\d{2}-\d{2}\.log")
"""日付ごとのログのファイルの名前の形（`YYYY-MM-DD.log`）。"""

UVICORN_LOGGER_NAMES: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")
"""ルートロガーへ寄せる uvicorn のロガー。"""


def local_today() -> date:
    """ローカルの今日の日付を返す。"""
    return datetime.now(tz=UTC).astimezone().date()


def _today() -> date:
    """ファイルハンドラが書くたびに見る今日の日付を返す。"""
    return local_today()


class _JsonLinesFormatter(logging.Formatter):
    """1 行 1 JSON（ts・level・name・msg・例外があれば exc）に整える。"""

    def format(self, record: logging.LogRecord) -> str:
        """ログの 1 件を JSON の 1 行にする。"""
        entry: dict[str, str] = {
            # ローカルの時刻を UTC オフセット付きの ISO 8601 で書く
            "ts": datetime.fromtimestamp(record.created, tz=UTC).astimezone().isoformat(),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class _DailyFileHandler(logging.Handler):
    """書くたびに今日の日付を見て、`{log_dir}/{YYYY-MM-DD}.log` へ追記するハンドラ。"""

    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self._log_dir = log_dir
        self._opened_date: date | None = None
        self._stream: IO[str] | None = None

    def emit(self, record: logging.LogRecord) -> None:
        """今日のファイルへ 1 行書く。日付が変わっていれば開き直す。"""
        try:
            today = _today()
            # 開いているファイルが今日のものか
            if self._stream is None or self._opened_date != today:
                # 違う: 前のファイルを閉じて今日のファイルを開く
                self._close_stream()
                path = self._log_dir / f"{today.isoformat()}{LOG_FILE_SUFFIX}"
                self._stream = path.open("a", encoding="utf-8")
                self._opened_date = today
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:  # noqa: BLE001  logging の作法: ログの失敗でアプリを止めない
            self.handleError(record)

    def close(self) -> None:
        """開いているファイルを閉じる。"""
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()

    def _close_stream(self) -> None:
        """開いているファイルがあれば閉じる。"""
        if self._stream is not None:
            self._stream.close()
            self._stream = None
            self._opened_date = None


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """sys.stderr へ書くハンドラ（setup_logging が付けたものと見分けるための型）。"""


def setup_logging(log_dir: Path, level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]) -> None:
    """標準の logging を日付ごとのファイルへ書くようにし、uvicorn のロガーもそこへ寄せる。"""
    # 1. ログの置き場所を作る
    log_dir.mkdir(parents=True, exist_ok=True)

    # 2. この関数が付けたハンドラが残っていれば外す（2 回呼んでも 1 組だけにする）
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, (_DailyFileHandler, _StderrHandler)):
            root.removeHandler(handler)
            handler.close()

    # 3. 日付ごとのファイルと、あれば stderr へ同じ書式で出す
    formatter = _JsonLinesFormatter()
    file_handler = _DailyFileHandler(log_dir)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    # pythonw では sys.stderr が無い
    if sys.stderr is not None:
        stderr_handler = _StderrHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        root.addHandler(stderr_handler)

    # 4. ルートロガーのレベルを設定する
    root.setLevel(level)

    # 5. uvicorn のロガーのハンドラを外し、ルートロガーへ伝える
    for name in UVICORN_LOGGER_NAMES:
        uvicorn_logger = logging.getLogger(name)
        for handler in list(uvicorn_logger.handlers):
            uvicorn_logger.removeHandler(handler)
        uvicorn_logger.propagate = True


def purge_old_logs(log_dir: Path, retention_days: int, today: date) -> int:
    """保持期間を過ぎた日付のログだけを消し、消したファイルの数を返す。"""
    cutoff = today - timedelta(days=retention_days)
    removed = 0
    for path in log_dir.iterdir():
        # `YYYY-MM-DD.log` の形でない名前は触らない
        if not LOG_FILE_NAME_PATTERN.fullmatch(path.name):
            continue
        try:
            log_date = date.fromisoformat(path.name.removesuffix(LOG_FILE_SUFFIX))
        except ValueError:
            # 存在しない日付（2026-13-40.log など）は触らない
            continue
        # 保持期間より前の日付なら消す
        if log_date < cutoff:
            path.unlink()
            removed += 1

    if removed:
        logger.info(f"古いログを消した（{removed} 件）")
    return removed
