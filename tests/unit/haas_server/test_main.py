"""haas_server/main.py（main）の単体テスト。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    """main が足したルートロガーのハンドラとレベルを元に戻す。"""
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level

    yield

    for handler in root.handlers:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logger")
def test_main_when_load_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """モデルの読み込みの失敗をログへ書いて終わる（異常系）。"""
    import haas_server.main as main_module

    # 準備
    log_file = tmp_path / "haas_server.log"

    def fail_to_load() -> NoReturn:
        """読み込みに失敗する。"""
        raise RuntimeError("GPU のメモリが足りない")

    monkeypatch.setattr(main_module, "LOG_FILE", log_file)
    monkeypatch.setattr(main_module, "load_engine", fail_to_load)

    # 実行
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["47826"])

    # 検証
    assert exc_info.value.code == 1
    written = log_file.read_text(encoding="utf-8")
    assert "[ERROR]" in written
    assert "GPU のメモリが足りない" in written
