"""integrations/openai/credentials.py（read_openai_api_key）の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_paste.shared.errors import StartupError


def _make_key_file(tmp_path: Path, content: str | None) -> Path:
    """API キーのファイルの置き場所を返す。content があればその中身で作り、None なら作らない。"""
    key_file = tmp_path / "secrets" / "openai_api_key"
    if content is not None:
        key_file.parent.mkdir(parents=True)
        key_file.write_text(content, encoding="utf-8")
    return key_file


def test_read_openai_api_key_when_env(tmp_path: Path) -> None:
    """環境変数を先に使う（正常系）。"""
    from voice_paste.integrations.openai.credentials import read_openai_api_key

    # 準備: 環境変数にも key_file にも別のキーがある
    key_file = _make_key_file(tmp_path, "sk-file\n")

    # 実行
    api_key = read_openai_api_key(key_file, {"OPENAI_API_KEY": " sk-env "})

    # 検証
    assert api_key.get_secret_value() == "sk-env"


def test_read_openai_api_key_when_file(tmp_path: Path) -> None:
    """環境変数が無ければファイルを読む（正常系）。"""
    from voice_paste.integrations.openai.credentials import read_openai_api_key

    # 準備
    key_file = _make_key_file(tmp_path, "sk-file\n")

    # 実行
    api_key = read_openai_api_key(key_file, {})

    # 検証
    assert api_key.get_secret_value() == "sk-file"


@pytest.mark.parametrize(
    "file_content",
    [
        pytest.param(None, id="file_missing"),
        pytest.param(" \n", id="file_blank"),
    ],
)
def test_read_openai_api_key_when_missing(tmp_path: Path, file_content: str | None) -> None:
    """どちらにも無ければ起動の失敗にする（異常系）。"""
    from voice_paste.integrations.openai.credentials import read_openai_api_key

    # 準備: key_file が無いか、中身が空白だけ
    key_file = _make_key_file(tmp_path, file_content)

    # 実行・検証
    with pytest.raises(StartupError, match="OPENAI_API_KEY") as exc_info:
        read_openai_api_key(key_file, {})
    assert str(key_file) in str(exc_info.value)
