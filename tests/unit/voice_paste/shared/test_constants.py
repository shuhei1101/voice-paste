"""shared/constants.py（resolve_app_paths）の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
"""リポジトリの直下。"""


def test_resolve_app_paths_when_data_dir(tmp_path: Path) -> None:
    """データの置き場所の下に全てを置く（正常系）。"""
    from voice_paste.shared.constants import resolve_app_paths

    # 実行
    paths = resolve_app_paths(tmp_path)

    # 検証（既定値の他は全てが data_dir の下で、checkout の上書きを読まず、フォルダは作られない）
    assert paths.settings_file == tmp_path / "settings.yaml"
    assert paths.legacy_settings_file == tmp_path / "settings.toml"
    assert paths.local_settings_file is None
    assert paths.defaults_file == REPO_ROOT / "config" / "defaults.yaml"
    assert paths.openai_api_key_file == tmp_path / "secrets" / "openai_api_key"
    assert paths.history_dir == tmp_path / "history"
    assert paths.log_dir == tmp_path / "log"
    assert paths.tmp_dir == tmp_path / "tmp"
    assert paths.token_file == tmp_path / "api_token"
    assert paths.ui_image_dir == tmp_path / "ui"
    assert paths.lock_file == tmp_path / "instance.lock"
    assert list(tmp_path.iterdir()) == []


def test_resolve_app_paths_when_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既定は platformdirs の置き場所（正常系）。"""
    from voice_paste.shared import constants
    from voice_paste.shared.constants import resolve_app_paths

    # 準備（from import と属性参照のどちらの書き方でも差し替わるよう両方に当てる）
    config_dir = tmp_path / "config"
    local_dir = tmp_path / "local"
    config_calls: list[dict[str, object]] = []

    def fake_user_config_dir(
        appname: str | None = None,
        appauthor: str | bool | None = None,
        version: str | None = None,
        roaming: bool = False,
        ensure_exists: bool = False,
    ) -> str:
        config_calls.append({"roaming": roaming})
        return str(config_dir)

    def fake_user_data_dir(
        appname: str | None = None,
        appauthor: str | bool | None = None,
        version: str | None = None,
        roaming: bool = False,
        ensure_exists: bool = False,
    ) -> str:
        return str(local_dir)

    monkeypatch.setattr("platformdirs.user_config_dir", fake_user_config_dir)
    monkeypatch.setattr("platformdirs.user_data_dir", fake_user_data_dir)
    monkeypatch.setattr(constants, "user_config_dir", fake_user_config_dir, raising=False)
    monkeypatch.setattr(constants, "user_data_dir", fake_user_data_dir, raising=False)

    # 実行
    paths = resolve_app_paths(None)

    # 検証
    assert paths.settings_file == config_dir / "settings.yaml"
    assert paths.legacy_settings_file == config_dir / "settings.toml"
    assert paths.local_settings_file == REPO_ROOT / "settings.local.yaml"
    assert paths.openai_api_key_file == config_dir / "secrets" / "openai_api_key"
    assert paths.history_dir == local_dir / "history"
    assert paths.log_dir == local_dir / "log"
    assert paths.tmp_dir == local_dir / "tmp"
    assert paths.token_file == local_dir / "api_token"
    assert config_calls == [{"roaming": True}]
