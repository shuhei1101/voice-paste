"""OpenAI の API キーを、環境変数か秘匿のファイルから読む。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import SecretStr

from voice_paste.shared.errors import StartupError

logger = logging.getLogger(__name__)

OPENAI_API_KEY_ENV: str = "OPENAI_API_KEY"
"""秘匿のファイルより先に読む環境変数の名前（OpenAI の公式 SDK と同じ名前）。"""


def read_openai_api_key(key_file: Path, environ: Mapping[str, str]) -> SecretStr:
    """環境変数があればその値を、無ければ key_file の中身を、前後の空白を除いて返す。どちらも無ければ起動の失敗にする。"""
    # 環境変数に API キーがあるか
    from_environ = environ.get(OPENAI_API_KEY_ENV, "").strip()
    if from_environ:
        # ある: 環境変数を使う
        return SecretStr(from_environ)

    # 無い: 秘匿のファイルを読む（ファイルが無い・読めないときは空として扱い、下で起動の失敗にする）
    try:
        from_file = key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        from_file = ""
    if from_file:
        return SecretStr(from_file)

    logger.error(f"OpenAI の API キーを読めなかった（環境変数 {OPENAI_API_KEY_ENV}・ファイル {key_file}）")
    raise StartupError(
        f"OpenAI の API キーがありません: 環境変数 {OPENAI_API_KEY_ENV} か {key_file} に置いてください"
    )
