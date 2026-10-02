"""server/token.py（create_token・write_token_file）の単体テスト。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

PORT = 47823
MIN_TOKEN_LENGTH = 43


def test_create_token() -> None:
    """呼ぶたびに違うトークンになる（正常系）。"""
    from voice_paste.server.token import create_token

    # 実行
    first = create_token().get_secret_value()
    second = create_token().get_secret_value()

    # 検証
    assert first != second
    assert len(first) >= MIN_TOKEN_LENGTH
    assert len(second) >= MIN_TOKEN_LENGTH


def test_write_token_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """トークンとポートを書く（正常系）。"""
    from voice_paste.server.token import create_token, write_token_file

    # 準備
    caplog.set_level(logging.INFO)
    token_file = tmp_path / "api_token"
    token = create_token()

    # 実行
    write_token_file(token_file, PORT, token)

    # 検証
    written = json.loads(token_file.read_text(encoding="utf-8"))
    assert written == {"port": PORT, "token": token.get_secret_value()}
    assert token.get_secret_value() not in caplog.text


def test_write_token_file_when_exists(tmp_path: Path) -> None:
    """前の起動のファイルを置き換える（正常系）。"""
    from voice_paste.server.token import create_token, write_token_file

    # 準備
    token_file = tmp_path / "api_token"
    token_file.write_text(json.dumps({"port": 1, "token": "old-token"}), encoding="utf-8")
    token = create_token()

    # 実行
    write_token_file(token_file, PORT, token)

    # 検証
    written = json.loads(token_file.read_text(encoding="utf-8"))
    assert written == {"port": PORT, "token": token.get_secret_value()}
    assert [path.name for path in tmp_path.iterdir()] == [token_file.name]
