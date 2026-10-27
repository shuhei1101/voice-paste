"""shared/logger.py（setup_logging・purge_old_logs）の単体テスト。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from tests.unit.log_helpers import read_log_records

TODAY = date(2026, 10, 1)
TOMORROW = date(2026, 10, 2)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """一時フォルダのログの置き場所を返す（フォルダはまだ無い）。"""
    return tmp_path / "log"


def _touch_logs(log_dir: Path, names: list[str]) -> None:
    """log_dir を作り、names の空のファイルを置く。"""
    log_dir.mkdir()
    for name in names:
        (log_dir / name).write_text("", encoding="utf-8")


# === setup_logging ===


def test_setup_logging(log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """今日のファイルに JSON Lines で書く（正常系）。"""
    from voice_paste.shared import logger as logger_module

    # 準備
    monkeypatch.setattr(logger_module, "_today", lambda: TODAY)
    app_logger = logging.getLogger("voice_paste.test_logger")

    # 実行
    logger_module.setup_logging(log_dir, "INFO")
    app_logger.info("設定を読んだ")
    app_logger.debug("出ない行")

    # 検証
    log_file = log_dir / f"{TODAY.isoformat()}.log"
    records = read_log_records(log_dir)
    assert [path.name for path in log_dir.glob("*.log")] == [log_file.name]
    assert len(records) == 1
    assert records[0]["level"] == "INFO"
    assert records[0]["name"] == "voice_paste.test_logger"
    assert records[0]["msg"] == "設定を読んだ"
    assert "設定を読んだ" in log_file.read_text(encoding="utf-8")
    assert datetime.fromisoformat(records[0]["ts"]).utcoffset() is not None


def test_setup_logging_when_called_twice(log_dir: Path) -> None:
    """2 回呼んでも二重に書かない（正常系）。"""
    from voice_paste.shared.logger import setup_logging

    # 準備
    app_logger = logging.getLogger("voice_paste.test_logger")

    # 実行
    setup_logging(log_dir, "INFO")
    setup_logging(log_dir, "INFO")
    app_logger.info("1 行だけ")

    # 検証
    assert len(read_log_records(log_dir)) == 1


def test_setup_logging_when_date_changed(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """日付が変われば次のファイルへ書く（正常系）。"""
    from voice_paste.shared import logger as logger_module

    # 準備
    current_day = {"value": TODAY}
    monkeypatch.setattr(logger_module, "_today", lambda: current_day["value"])
    app_logger = logging.getLogger("voice_paste.test_logger")
    logger_module.setup_logging(log_dir, "INFO")

    # 実行
    app_logger.info("今日の行")
    current_day["value"] = TOMORROW
    app_logger.info("翌日の行")

    # 検証
    today_lines = (log_dir / f"{TODAY.isoformat()}.log").read_text(encoding="utf-8")
    tomorrow_lines = (log_dir / f"{TOMORROW.isoformat()}.log").read_text(encoding="utf-8")
    assert len(today_lines.splitlines()) == 1
    assert "今日の行" in today_lines
    assert len(tomorrow_lines.splitlines()) == 1
    assert "翌日の行" in tomorrow_lines


def test_setup_logging_when_uvicorn_logger(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uvicorn のログも同じファイルへ寄せる（正常系）。"""
    from voice_paste.shared import logger as logger_module

    # 準備
    monkeypatch.setattr(logger_module, "_today", lambda: TODAY)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.addHandler(logging.NullHandler())

    # 実行
    logger_module.setup_logging(log_dir, "INFO")
    uvicorn_logger.info("サーバーを起動した")

    # 検証
    records = read_log_records(log_dir)
    assert uvicorn_logger.handlers == []
    assert len(records) == 1
    assert records[0]["name"] == "uvicorn.error"
    assert records[0]["msg"] == "サーバーを起動した"


# === purge_old_logs ===


def test_purge_old_logs(log_dir: Path) -> None:
    """保持期間を過ぎた日付のログだけ削除する（正常系）。"""
    from voice_paste.shared.logger import purge_old_logs

    # 準備（保持 1 日: 今日・1 日前・2 日前）
    _touch_logs(log_dir, ["2026-10-01.log", "2026-09-30.log", "2026-09-29.log"])

    # 実行
    removed = purge_old_logs(log_dir, 1, TODAY)

    # 検証
    assert removed == 1
    assert sorted(path.name for path in log_dir.iterdir()) == [
        "2026-09-30.log",
        "2026-10-01.log",
    ]


def test_purge_old_logs_when_other_names(log_dir: Path) -> None:
    """日付の形式でない名前は削除しない（正常系）。"""
    from voice_paste.shared.logger import purge_old_logs

    # 準備（保持 1 日: 日付の形式でない名前 2 つと 10 日前）
    _touch_logs(log_dir, ["notes.log", "2026-13-40.log", "2026-09-21.log"])

    # 実行
    removed = purge_old_logs(log_dir, 1, TODAY)

    # 検証
    assert removed == 1
    assert sorted(path.name for path in log_dir.iterdir()) == [
        "2026-13-40.log",
        "notes.log",
    ]
