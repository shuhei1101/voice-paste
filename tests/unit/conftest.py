"""単体テスト（新しい構成）の共通フィクスチャ。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

# setup_logging が handlers と propagate を入れ替える uvicorn のロガー
UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _is_pytest_handler(handler: logging.Handler) -> bool:
    """pytest 自身がログの収集に付けたハンドラか。"""
    return type(handler).__module__.startswith("_pytest")


@pytest.fixture
def repo_root() -> Path:
    """リポジトリの直下（settings.sample.toml と .env.sample の置き場所）を返す。"""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """setup_logging が入れ替えるルートロガーと uvicorn のロガーを、テストの後に元へ戻す。"""
    root = logging.getLogger()
    saved_root_handlers = list(root.handlers)
    saved_root_level = root.level
    saved_uvicorn = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
            logging.getLogger(name).level,
        )
        for name in UVICORN_LOGGER_NAMES
    }

    yield

    # テストの中で付いたハンドラを閉じてから外す（ログのファイルを開いたままにしない）。pytest の収集用は残す
    for handler in list(root.handlers):
        if handler not in saved_root_handlers and not _is_pytest_handler(handler):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_root_level)
    for name, (handlers, propagate, level) in saved_uvicorn.items():
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.handlers[:] = handlers
        logger.propagate = propagate
        logger.setLevel(level)
