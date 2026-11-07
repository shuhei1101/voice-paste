"""haas_server/main.py（parse_args・load_engine・main）の単体テスト。"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import MagicMock

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

    def fail_to_load(args: Any) -> NoReturn:
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


def test_parse_args() -> None:
    """全ての引数を読む（正常系）。"""
    from haas_server.main import ServerArgs, parse_args

    # 実行
    result = parse_args(["47824", "x/model", "float32", "cpu"])

    # 検証
    assert result == ServerArgs(port=47824, model="x/model", dtype="float32", device="cpu")


def test_parse_args_when_port_only() -> None:
    """ポートだけなら既定値（正常系）。"""
    from haas_server.main import ServerArgs, parse_args

    # 実行
    result = parse_args(["47824"])

    # 検証
    assert result == ServerArgs(
        port=47824, model="third-intelligence/Haas-ja-v1.0", dtype="auto", device="cuda"
    )


def test_parse_args_when_dtype_invalid() -> None:
    """計算の精度が読めない（異常系）。"""
    from haas_server.main import parse_args

    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["47824", "x/model", "int8", "cuda"])
    assert exc_info.value.code == 2


@pytest.fixture
def fake_haas_asr(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """haas_asr と torch を sys.modules の偽物に差し替える。"""
    haas_asr = MagicMock(name="haas_asr")
    torch = SimpleNamespace(bfloat16="torch.bfloat16", float16="torch.float16", float32="torch.float32")
    monkeypatch.setitem(sys.modules, "haas_asr", haas_asr)
    monkeypatch.setitem(sys.modules, "torch", torch)
    return haas_asr


def test_load_engine(fake_haas_asr: MagicMock) -> None:
    """引数と調整の値を haas_asr に渡す（正常系）。"""
    from haas_server.app import TranscribeOptions
    from haas_server.main import ServerArgs, load_engine

    # 準備
    args = ServerArgs(port=47824, model="x/model", dtype="float32", device="cpu")
    options = TranscribeOptions(batch_size=8, chunk_sec=15.0)
    samples = MagicMock(name="samples")

    # 実行
    engine = load_engine(args)
    engine.transcribe_longform(samples, None, options)

    # 検証
    fake_haas_asr.load_model.assert_called_once_with("x/model", device="cpu", dtype="torch.float32")
    fake_haas_asr.transcribe_longform.assert_called_once_with(
        fake_haas_asr.load_model.return_value,
        samples,
        batch_size=8,
        separator="",
        vocabulary=None,
        guard=True,
        chunk_seconds=15.0,
        search_seconds=2.0,
        window_seconds=0.1,
    )
    assert engine.dtype == "float32"
    assert engine.device == "cpu"
    assert engine.model_name == "x/model"


def test_load_engine_when_auto(fake_haas_asr: MagicMock) -> None:
    """auto はそのまま渡す（正常系）。"""
    from haas_server.main import ServerArgs, load_engine

    # 準備
    args = ServerArgs(port=47824, model="x/model", dtype="auto", device="cuda")

    # 実行
    load_engine(args)

    # 検証
    fake_haas_asr.load_model.assert_called_once_with("x/model", device="cuda", dtype="auto")
