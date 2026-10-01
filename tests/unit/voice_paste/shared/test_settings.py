"""shared/settings.py（load_settings・save_settings）の単体テスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

SETTINGS_FILE_NAME = "settings.toml"


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """一時フォルダの settings.toml のパスを返す（ファイルはまだ無い）。"""
    return tmp_path / SETTINGS_FILE_NAME


# === load_settings ===


def test_load_settings_when_missing(settings_file: Path) -> None:
    """無ければ既定値で作る（正常系）。"""
    from voice_paste.shared.settings import Settings, load_settings

    # 実行
    settings = load_settings(settings_file)

    # 検証
    assert settings == Settings()
    assert settings_file.exists()


def test_load_settings(settings_file: Path) -> None:
    """書いた値を読む（正常系）。"""
    from voice_paste.shared.settings import (
        CopyOnlySettings,
        LocalWhisperSettings,
        Settings,
        TranscriptionSettings,
        load_settings,
    )

    # 準備
    settings_file.write_text(
        '[transcription.local_whisper]\nmodel = "small"\n\n[[outputs]]\nid = "copy_only"\n',
        encoding="utf-8",
    )

    # 実行
    settings = load_settings(settings_file)

    # 検証（書いていない項目は既定値）
    assert settings == Settings(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small")),
        outputs=[CopyOnlySettings()],
    )


def test_load_settings_when_sample_file(repo_root: Path) -> None:
    """リポジトリの見本は既定値と一致する（正常系）。"""
    from voice_paste.shared.settings import Settings, load_settings

    # 実行
    settings = load_settings(repo_root / "settings.sample.toml")

    # 検証
    assert settings == Settings()


def test_load_settings_when_invalid_value(settings_file: Path) -> None:
    """合わない値はキーを示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text(
        '[transcription.local_whisper]\nbeam_size = "x"\n', encoding="utf-8"
    )

    # 実行・検証
    with pytest.raises(SettingsError, match=r"transcription\.local_whisper\.beam_size"):
        load_settings(settings_file)


def test_load_settings_when_unknown_key(settings_file: Path) -> None:
    """知らないキーを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text("[recording]\nvolum_percent = 30\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match=r"recording\.volum_percent"):
        load_settings(settings_file)


def test_load_settings_when_duplicate_output_id(settings_file: Path) -> None:
    """出力先の ID の重なりを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text(
        '[[outputs]]\nid = "copy_only"\n\n[[outputs]]\nid = "copy_only"\n',
        encoding="utf-8",
    )

    # 実行・検証
    with pytest.raises(SettingsError, match="outputs"):
        load_settings(settings_file)


def test_load_settings_when_broken_toml(settings_file: Path) -> None:
    """壊れた TOML を断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text("[recording\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError):
        load_settings(settings_file)


# === save_settings ===


def test_save_settings_when_comments(settings_file: Path) -> None:
    """コメントを保ったまま値を書き換える（正常系）。"""
    from voice_paste.shared.settings import (
        HotkeySettings,
        Settings,
        load_settings,
        save_settings,
    )

    # 準備
    settings_file.write_text(
        '# 録音まわりのホットキー\n[hotkeys]\n# 録音を始めるキー\nstart = "<ctrl>+<alt>+d"\n',
        encoding="utf-8",
    )
    new_settings = Settings(hotkeys=HotkeySettings(start="<ctrl>+<alt>+s"))

    # 実行
    save_settings(settings_file, new_settings)

    # 検証
    text = settings_file.read_text(encoding="utf-8")
    assert "# 録音まわりのホットキー" in text
    assert "# 録音を始めるキー" in text
    assert load_settings(settings_file).hotkeys.start == "<ctrl>+<alt>+s"


def test_save_settings_when_restart_item_changed(settings_file: Path) -> None:
    """再起動が要る項目が変われば True（正常系）。"""
    from voice_paste.shared.settings import (
        LocalWhisperSettings,
        Settings,
        TranscriptionSettings,
        save_settings,
    )

    # 準備（large-v3 から small へ変える）
    settings_file.write_text(
        '[transcription.local_whisper]\nmodel = "large-v3"\n', encoding="utf-8"
    )
    new_settings = Settings(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small"))
    )

    # 実行
    restart_required = save_settings(settings_file, new_settings)

    # 検証
    assert restart_required is True


def test_save_settings_when_immediate_item_changed(settings_file: Path) -> None:
    """即時に効く項目だけなら False（正常系）。"""
    from voice_paste.shared.settings import HotkeySettings, Settings, save_settings

    # 準備
    settings_file.write_text(
        '[hotkeys]\nstart = "<ctrl>+<alt>+d"\n', encoding="utf-8"
    )
    new_settings = Settings(hotkeys=HotkeySettings(start="<ctrl>+<alt>+s"))

    # 実行
    restart_required = save_settings(settings_file, new_settings)

    # 検証
    assert restart_required is False


def test_save_settings_when_missing(tmp_path: Path) -> None:
    """無ければフォルダごと作る（正常系）。"""
    from voice_paste.shared.settings import Settings, save_settings

    # 準備
    path = tmp_path / "not_created" / SETTINGS_FILE_NAME
    new_settings = Settings()

    # 実行
    restart_required = save_settings(path, new_settings)

    # 検証
    written = tomllib.loads(path.read_text(encoding="utf-8"))
    assert restart_required is False
    assert path.exists()
    assert "glossary_path" not in written


def test_save_settings_when_invalid_existing(settings_file: Path) -> None:
    """壊れたファイルは書き直して再起動が要るとする（正常系）。"""
    from voice_paste.shared.settings import Settings, load_settings, save_settings

    # 準備
    settings_file.write_text("[recording\n", encoding="utf-8")

    # 実行
    restart_required = save_settings(settings_file, Settings())

    # 検証
    assert restart_required is True
    assert load_settings(settings_file) == Settings()


def test_save_settings_when_glossary_reset(settings_file: Path) -> None:
    """用語集の場所を既定（None）に戻すとキーを消す（正常系）。"""
    from voice_paste.shared.settings import Settings, load_settings, save_settings

    # 準備
    settings_file.write_text('glossary_path = "C:/x/yogo.csv"\n', encoding="utf-8")

    # 実行
    save_settings(settings_file, Settings())

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert "glossary_path" not in written
    assert load_settings(settings_file).glossary_path is None
