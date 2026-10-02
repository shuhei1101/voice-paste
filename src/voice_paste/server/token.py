"""起動ごとのトークンの作成と、トークンのファイルへの書き出し。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from pydantic import SecretStr

logger = logging.getLogger(__name__)

TOKEN_BYTES: int = 32
"""secrets.token_urlsafe に渡す乱数のバイト数。256 bit で推測できない長さにする。"""

TOKEN_FILE_ENCODING: str = "utf-8"
"""トークンのファイルの文字コード。"""

TEMPORARY_SUFFIX: str = ".tmp"
"""トークンのファイルを置き換える前に書く一時ファイルの拡張子。"""


def create_token() -> SecretStr:
    """起動ごとのトークンを作る。ファイルには書かない（待ち受けを始めてから write_token_file で書く）。"""
    return SecretStr(secrets.token_urlsafe(TOKEN_BYTES))


def write_token_file(token_file: Path, port: int, token: SecretStr) -> None:
    """今回のトークンとポートを、同じフォルダの一時ファイルへ書いてからトークンのファイルへ置き換える。"""
    # 1. 読む側が書きかけを読まないよう、一時ファイルに書いてから置き換える
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_file.with_name(token_file.name + TEMPORARY_SUFFIX)
    temporary.write_text(
        json.dumps({"port": port, "token": token.get_secret_value()}), encoding=TOKEN_FILE_ENCODING
    )
    os.replace(temporary, token_file)
    logger.info(f"トークンのファイルを書いた（{token_file}・ポート: {port}）")
