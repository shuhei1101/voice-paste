"""main.py（parse_args・並走の間の main）の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.log_helpers import read_log_records


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """--data-dir に渡す空の一時フォルダを返す。"""
    path = tmp_path / "data"
    path.mkdir()
    return path


# === parse_args ===


def test_parse_args() -> None:
    """データの置き場所だけを読む（正常系）。"""
    from voice_paste.main import parse_args

    # 実行
    args = parse_args(["--data-dir", "C:/tmp/vp"])

    # 検証
    assert args.data_dir == Path("C:/tmp/vp")
    assert args.migrate_env is None


def test_parse_args_when_migrate_env() -> None:
    """移す .env も読む（正常系）。"""
    from voice_paste.main import parse_args

    # 実行
    args = parse_args(["--data-dir", "C:/tmp/vp", "--migrate-env", "C:/repo/.env"])

    # 検証
    assert args.migrate_env == Path("C:/repo/.env")


def test_parse_args_when_no_data_dir() -> None:
    """データの置き場所が無ければ終わる（異常系）。"""
    from voice_paste.main import parse_args

    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        parse_args([])
    assert exc_info.value.code == 2


# === main ===


def test_main(data_dir: Path) -> None:
    """設定を読んでログに書き 0 を返す（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import Settings, load_settings

    # 実行
    exit_code = main(["--data-dir", str(data_dir)])

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml") == Settings()
    assert "設定を読んだ" in str(read_log_records(data_dir / "log", "INFO"))


def test_main_when_migrate_env(data_dir: Path, tmp_path: Path) -> None:
    """.env を移してから読む（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import load_settings

    # 準備
    env_path = tmp_path / ".env"
    env_content = "WHISPER_MODEL=small\n"
    env_path.write_text(env_content, encoding="utf-8")

    # 実行
    exit_code = main(["--data-dir", str(data_dir), "--migrate-env", str(env_path)])

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml").transcription.local_whisper.model == "small"
    assert env_path.read_text(encoding="utf-8") == env_content
    assert not (tmp_path / ".env.migrated").exists()


def test_main_when_settings_exists_and_migrate_env(data_dir: Path, tmp_path: Path) -> None:
    """設定ファイルがあれば移さない（異常系）。"""
    from voice_paste.main import main

    # 準備
    settings_file = data_dir / "settings.toml"
    settings_file.write_text('[hotkeys]\nstart = "<ctrl>+<alt>+s"\n', encoding="utf-8")
    settings_before = settings_file.read_bytes()
    env_path = tmp_path / ".env"
    env_path.write_text("WHISPER_MODEL=small\n", encoding="utf-8")

    # 実行
    exit_code = main(["--data-dir", str(data_dir), "--migrate-env", str(env_path)])

    # 検証
    assert exit_code == 1
    assert settings_file.read_bytes() == settings_before
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1


def test_main_when_invalid_settings(data_dir: Path) -> None:
    """設定が合わなければ 1 を返す（異常系）。"""
    from voice_paste.main import main

    # 準備
    (data_dir / "settings.toml").write_text(
        '[transcription.local_whisper]\nbeam_size = "x"\n', encoding="utf-8"
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)])

    # 検証
    assert exit_code == 1
    assert "transcription.local_whisper.beam_size" in str(
        read_log_records(data_dir / "log", "ERROR")
    )
