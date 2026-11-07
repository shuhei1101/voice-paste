"""shared/settings.py（load_settings・load_default_settings・save_settings・reset_settings・migrate_settings_toml・inherit_transcribing_show_hotkeys・find_hotkey_overlaps・find_glossary_name_overlaps・find_glossary_preset_name_overlaps・join_hint_words・find_hint_preset_name_overlaps・EdgePhraseSettings・migrate_ai_chat・build_settings_model・Settings の確かめ）の単体テスト。"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest

from tests.unit.voice_paste.settings_helpers import DEFAULTS_FILE, make_test_document
from voice_paste.shared.os_kind import OsKind

if TYPE_CHECKING:
    from tests.unit.voice_paste.settings_helpers import MakeSettings
    from voice_paste.shared.constants import AppPaths
    from voice_paste.shared.settings import OutputSettingsBase, Settings

LOCAL_SETTINGS_FILE_NAME = "settings.local.yaml"
"""checkout の上書きのファイル名。"""

BROKEN_YAML = "hotkeys:\n  start: <ctrl>+<alt>+a\n pause: <ctrl>+<alt>+p\n"
"""3 行目の字下げが崩れた YAML。"""

BROKEN_TOML = "[recording\n"
"""表の見出しが閉じていない TOML。"""

HOTKEY_A = "<ctrl>+<alt>+a"
"""既定値と違う、環境の値に書くホットキー。"""

HOTKEY_B = "<ctrl>+<alt>+b"
"""既定値と違う、checkout の上書きか settings.toml に書くホットキー。"""

HOTKEY_C = "<ctrl>+<alt>+s"
"""既定値と違う、保存する設定のホットキー。"""

AI_CHAT_SETTINGS_YAML = (
    "outputs:\n"
    "  - id: paste_only\n"
    "    hotkey: <ctrl>+<alt>+v\n"
    "  - id: ai_chat\n"
    "    open_delay_sec: 2.0\n"
    "    targets:\n"
    "      - name: ChatGPT\n"
    "        url: https://chatgpt.com\n"
    "        hotkey: <ctrl>+<alt>+1\n"
    "        enabled: true\n"
    "      - name: Claude\n"
    "        url: https://claude.ai/new\n"
    "        hotkey: <ctrl>+<alt>+3\n"
    "        enabled: false\n"
)
"""古い AI チャットの設定（送信先 2 件、開くまでの間 2.0 秒）を残した settings.yaml。"""

SPECIAL_STRINGS = [
    "*",
    "yes",
    "no",
    "on",
    "off",
    "0123",
    "a: b",
    "null",
    "~",
    "ご視聴ありがとうございました",
]
"""YAML で文字列でなくなるか、特別な意味を持つ文言と、日本語の文言。"""


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """一時フォルダの置き場所を返す。既定値はリポジトリの config/defaults.yaml、checkout の上書きは一時フォルダの checkout の下（どちらの設定のファイルもまだ無い）。"""
    import dataclasses

    from voice_paste.shared.constants import resolve_app_paths

    resolved = resolve_app_paths(tmp_path / "data")
    return dataclasses.replace(
        resolved,
        defaults_file=DEFAULTS_FILE,
        local_settings_file=tmp_path / "checkout" / LOCAL_SETTINGS_FILE_NAME,
    )


def _write(path: Path, text: str) -> None:
    """親のフォルダを作り、UTF-8 で書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _updated(settings: Settings, table: str, **values: Any) -> Settings:
    """設定の 1 つのまとまりの項目を替えたコピーを返す（検証しない）。"""
    group = getattr(settings, table)
    return settings.model_copy(update={table: group.model_copy(update=values)})


def _without_none(value: Any) -> Any:
    """TOML に書けない None の項目を、表と一覧の中から外したコピーを返す。"""
    # 表か
    if isinstance(value, dict):
        # そう: None の項目を外して中もたどる
        return {key: _without_none(item) for key, item in value.items() if item is not None}
    # 一覧か
    if isinstance(value, list):
        # そう: 要素をたどる
        return [_without_none(item) for item in value]
    # それ以外: そのまま返す
    return value


def _write_toml(path: Path, values: dict[str, Any]) -> str:
    """設定と同じ構造の dict を TOML で書き、書いた文字列を返す。"""
    import tomlkit

    text = tomlkit.dumps(_without_none(values))
    _write(path, text)
    return text


# === load_settings ===


def test_load_settings_when_only_defaults(
    paths: AppPaths, settings_model: type[Settings], default_settings: Settings
) -> None:
    """環境の値と checkout の上書きが無ければ既定値で動き、ファイルを作らない（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert settings == default_settings
    assert not paths.settings_file.exists()


def test_load_settings(
    paths: AppPaths, settings_model: type[Settings], make_settings: MakeSettings
) -> None:
    """環境の値に書いたキーだけが既定値に勝つ（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(
        paths.settings_file,
        "transcription:\n"
        "  local_whisper:\n"
        "    model: small\n"
        "outputs:\n"
        "  - id: copy_only\n"
        "    hotkey: <ctrl>+<alt>+c\n",
    )

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証（書いていない項目は既定値）
    assert settings == make_settings(
        {
            "transcription": {"local_whisper": {"model": "small"}},
            "outputs": [{"id": "copy_only", "hotkey": "<ctrl>+<alt>+c"}],
        }
    )
    assert [type(output) for output in settings.outputs] == [CopyOnlySettings]


def test_load_settings_when_local_override(
    paths: AppPaths, settings_model: type[Settings], default_settings: Settings
) -> None:
    """checkout の上書きが環境の値に勝つ（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    assert paths.local_settings_file is not None
    settings_text = f"hotkeys:\n  start: {HOTKEY_A}\n"
    local_text = f"hotkeys:\n  start: {HOTKEY_B}\n"
    _write(paths.settings_file, settings_text)
    _write(paths.local_settings_file, local_text)

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert settings.hotkeys.start == HOTKEY_B
    assert settings.hotkeys.cancel == default_settings.hotkeys.cancel
    assert paths.settings_file.read_text(encoding="utf-8") == settings_text
    assert paths.local_settings_file.read_text(encoding="utf-8") == local_text


def test_load_settings_when_local_override_disabled(
    paths: AppPaths, settings_model: type[Settings], default_settings: Settings
) -> None:
    """local_settings_file が None なら checkout の上書きを読まない（正常系）。"""
    import dataclasses

    from voice_paste.shared.settings import load_settings

    # 準備（同じフォルダに settings.local.yaml を置いておく）
    disabled = dataclasses.replace(paths, local_settings_file=None)
    _write(
        paths.settings_file.parent / LOCAL_SETTINGS_FILE_NAME, f"hotkeys:\n  start: {HOTKEY_B}\n"
    )

    # 実行
    settings = load_settings(disabled, settings_model)

    # 検証
    assert settings.hotkeys.start == default_settings.hotkeys.start


def test_load_settings_when_only_settings_toml(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """settings.yaml が無く settings.toml があれば移してから読む（正常系）。"""
    from voice_paste.shared.settings import load_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    toml_text = f'[hotkeys]\nstart = "{HOTKEY_B}"\n'
    _write(paths.legacy_settings_file, toml_text)

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {"hotkeys": {"start": HOTKEY_B}}
    assert settings.hotkeys.start == HOTKEY_B
    assert paths.legacy_settings_file.read_text(encoding="utf-8") == toml_text


def test_load_settings_when_both_files(paths: AppPaths, settings_model: type[Settings]) -> None:
    """settings.yaml があれば settings.toml を読まない（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_text = f"hotkeys:\n  start: {HOTKEY_A}\n"
    _write(paths.settings_file, settings_text)
    _write(paths.legacy_settings_file, f'[hotkeys]\nstart = "{HOTKEY_B}"\n')

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert settings.hotkeys.start == HOTKEY_A
    assert paths.settings_file.read_text(encoding="utf-8") == settings_text


@pytest.mark.parametrize(
    ("content", "expected_key"),
    [
        pytest.param(
            "transcription:\n  local_whisper:\n    beam_size: x\n",
            r"transcription\.local_whisper\.beam_size",
            id="beam_size",
        ),
        pytest.param(
            "transcription:\n  engine: gemini\n",
            r"transcription\.engine",
            id="engine_unknown",
        ),
    ],
)
def test_load_settings_when_invalid_value(
    paths: AppPaths, settings_model: type[Settings], content: str, expected_key: str
) -> None:
    """合わない値はキーを示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(paths.settings_file, content)

    # 実行・検証
    with pytest.raises(SettingsError, match=expected_key):
        load_settings(paths, settings_model)


@pytest.mark.parametrize(
    ("written_fields", "expected_fields"),
    [
        pytest.param(("settings_file",), ("settings_file",), id="settings_file"),
        pytest.param(
            ("settings_file", "local_settings_file"),
            ("settings_file", "local_settings_file"),
            id="settings_file_and_local",
        ),
        pytest.param((), ("defaults_file",), id="defaults_only"),
    ],
)
def test_load_settings_when_invalid_value_paths(
    paths: AppPaths,
    settings_model: type[Settings],
    tmp_path: Path,
    written_fields: tuple[str, ...],
    expected_fields: tuple[str, ...],
) -> None:
    """重ねた値が合わないときは、読んだ環境の値と checkout の上書きのファイルを paths に持つ（異常系）。"""
    import dataclasses

    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備（既定値を一時フォルダへ写して beam_size を合わない値にし、渡したファイルにも合わない値を置く）
    copied = dataclasses.replace(paths, defaults_file=tmp_path / "config" / "defaults.yaml")
    copied.defaults_file.parent.mkdir(parents=True)
    copied.defaults_file.write_text(
        DEFAULTS_FILE.read_text(encoding="utf-8").replace("beam_size: 10", 'beam_size: "x"'),
        encoding="utf-8",
    )
    for field in written_fields:
        _write(getattr(copied, field), 'transcription:\n  local_whisper:\n    beam_size: "x"\n')

    # 実行・検証
    with pytest.raises(SettingsError, match=r"transcription\.local_whisper\.beam_size") as exc_info:
        load_settings(copied, settings_model)
    assert exc_info.value.paths == tuple(getattr(copied, field) for field in expected_fields)


@pytest.mark.parametrize(
    ("content", "expected_key"),
    [
        pytest.param("recording:\n  volum_percent: 30\n", r"recording\.volum_percent", id="typo"),
        pytest.param(
            "transcription:\n  openai:\n    modle: gpt-4o-mini-transcribe\n",
            r"transcription\.openai\.modle",
            id="openai_typo",
        ),
    ],
)
def test_load_settings_when_unknown_key(
    paths: AppPaths, settings_model: type[Settings], content: str, expected_key: str
) -> None:
    """知らないキーを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(paths.settings_file, content)

    # 実行・検証
    with pytest.raises(SettingsError, match=expected_key):
        load_settings(paths, settings_model)


def test_load_settings_when_duplicate_output_id(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """出力先の ID の重なりを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(
        paths.settings_file,
        "outputs:\n"
        "  - id: copy_only\n"
        "    hotkey: <ctrl>+<alt>+c\n"
        "  - id: copy_only\n"
        "    hotkey: <ctrl>+<alt>+x\n",
    )

    # 実行・検証
    with pytest.raises(SettingsError, match="outputs"):
        load_settings(paths, settings_model)


@pytest.mark.parametrize(
    "broken_field",
    [
        pytest.param("settings_file", id="settings_file"),
        pytest.param("local_settings_file", id="local_settings_file"),
        pytest.param("defaults_file", id="defaults_file"),
    ],
)
def test_load_settings_when_broken_yaml(
    paths: AppPaths, settings_model: type[Settings], tmp_path: Path, broken_field: str
) -> None:
    """読めない YAML は、読めなかったファイルと行・列を示して断る（異常系）。"""
    import dataclasses

    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備（既定値を一時フォルダへ写し、3 つのファイルを読めるものにしてから 1 つを崩す）
    copied = dataclasses.replace(paths, defaults_file=tmp_path / "config" / "defaults.yaml")
    assert copied.local_settings_file is not None
    copied.defaults_file.parent.mkdir(parents=True)
    shutil.copyfile(DEFAULTS_FILE, copied.defaults_file)
    _write(copied.settings_file, f"hotkeys:\n  start: {HOTKEY_A}\n")
    _write(copied.local_settings_file, f"hotkeys:\n  start: {HOTKEY_B}\n")
    broken_path: Path = getattr(copied, broken_field)
    _write(broken_path, BROKEN_YAML)
    settings_text = copied.settings_file.read_text(encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match=r"3行目 \d+列目") as exc_info:
        load_settings(copied, settings_model)
    assert str(broken_path) in str(exc_info.value)
    assert exc_info.value.paths == (broken_path,)
    assert copied.settings_file.read_text(encoding="utf-8") == settings_text


def test_load_settings_when_defaults_missing(
    paths: AppPaths, settings_model: type[Settings], tmp_path: Path
) -> None:
    """既定値が無ければ断る（異常系）。"""
    import dataclasses

    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    missing = dataclasses.replace(paths, defaults_file=tmp_path / "config" / "defaults.yaml")

    # 実行・検証
    with pytest.raises(SettingsError) as exc_info:
        load_settings(missing, settings_model)
    assert str(missing.defaults_file) in str(exc_info.value)


def test_load_settings_when_broken_settings_toml(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """移すときに settings.toml を読めなければ、settings.yaml を作らずに断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(paths.legacy_settings_file, BROKEN_TOML)

    # 実行・検証
    with pytest.raises(SettingsError, match="settings.toml"):
        load_settings(paths, settings_model)
    assert not paths.settings_file.exists()


def test_load_settings_when_ai_chat_remains(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """古い AI チャットの設定が残っていても読め、プリセットに読み替える（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset, load_settings

    # 準備
    _write(paths.settings_file, AI_CHAT_SETTINGS_YAML)

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert [output.id for output in settings.outputs] == ["paste_only"]
    assert settings.presets == [
        BrowserPreset(
            title="ChatGPT",
            url="https://chatgpt.com",
            hotkey="<ctrl>+<alt>+1",
            enabled=True,
            send_enter=True,
        ),
        BrowserPreset(
            title="Claude",
            url="https://claude.ai/new",
            hotkey="<ctrl>+<alt>+3",
            enabled=False,
            send_enter=True,
        ),
    ]
    assert settings.preset_options.browser.open_delay_sec == 2.0
    assert paths.settings_file.read_text(encoding="utf-8") == AI_CHAT_SETTINGS_YAML


def test_load_settings_when_invalid_preset(paths: AppPaths, settings_model: type[Settings]) -> None:
    """合わないプリセットはキーを示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(
        paths.settings_file,
        "presets:\n  - kind: endpoint\n    title: 受信先\n    url: ftp://x\n",
    )

    # 実行・検証
    with pytest.raises(SettingsError, match=r"presets\[0\].*url"):
        load_settings(paths, settings_model)


def test_load_settings_when_sample_file(
    paths: AppPaths, settings_model: type[Settings], repo_root: Path
) -> None:
    """リポジトリの見本は、既定値に重ねて設定のモデルの検証に通る（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    paths.settings_file.parent.mkdir(parents=True)
    shutil.copyfile(repo_root / "settings.sample.yaml", paths.settings_file)

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert isinstance(settings, settings_model)


@pytest.mark.parametrize(
    "layer_field",
    [
        pytest.param("settings_file", id="settings_file"),
        pytest.param("local_settings_file", id="local_settings_file"),
    ],
)
def test_load_settings_when_only_show_hotkeys(
    paths: AppPaths, settings_model: type[Settings], layer_field: str
) -> None:
    """録音の画面のホットキーの表示だけを書いたレイヤーは、文字起こし中の表示を既定値で読む（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(getattr(paths, layer_field), "ui:\n  show_hotkeys: false\n")

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert settings.ui.show_hotkeys is False
    assert settings.ui.transcribing_show_hotkeys is True


def test_load_settings_when_no_hint_presets(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """hint_presets のキーが無い settings.yaml を読める（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    _write(paths.settings_file, "transcription:\n  local_whisper:\n    model: small\n")

    # 実行
    settings = load_settings(paths, settings_model)

    # 検証
    assert settings.hint_presets == []


# === load_default_settings ===


@pytest.mark.parametrize("os_kind", [pytest.param(kind, id=kind.value) for kind in OsKind])
def test_load_default_settings(settings_model: type[Settings], os_kind: OsKind) -> None:
    """リポジトリの既定値は、全ての OS で設定のモデルの検証に通る（正常系）。"""
    from voice_paste.shared.settings import load_default_settings

    # 実行
    settings = load_default_settings(DEFAULTS_FILE, settings_model, os_kind=os_kind)

    # 検証
    assert isinstance(settings, settings_model)


def test_load_default_settings_when_linux(settings_model: type[Settings]) -> None:
    """Linux では OS の上書きの値になる（正常系）。"""
    from voice_paste.shared.settings import load_default_settings

    # 実行
    settings = load_default_settings(DEFAULTS_FILE, settings_model, os_kind=OsKind.LINUX)

    # 検証
    assert settings.recording.lower_volume is False
    assert settings.transcription.local_whisper.device == "cpu"
    assert settings.transcription.local_whisper.compute_type == "int8"
    assert (settings.hotkeys.start, settings.hotkeys.pause, settings.hotkeys.cancel) == (
        "<cmd>+<alt>+d",
        "<cmd>+<alt>+z",
        "<cmd>+<alt>+q",
    )
    assert {output.id: output.hotkey for output in settings.outputs} == {
        "paste_and_send": "<cmd>+<alt>+d",
        "paste_only": "<cmd>+<alt>+v",
        "copy_only": "<cmd>+<alt>+c",
    }


def test_load_default_settings_when_missing_key(
    settings_model: type[Settings], tmp_path: Path
) -> None:
    """既定値に欠けたキーがあれば断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_default_settings
    from voice_paste.shared.yaml_document import (
        delete_key,
        read_yaml_document,
        write_yaml_document,
    )

    # 準備（hotkeys.cancel を除いた既定値のファイル）
    defaults_file = tmp_path / "defaults.yaml"
    document = read_yaml_document(DEFAULTS_FILE)
    delete_key(document, ("hotkeys", "cancel"))
    write_yaml_document(defaults_file, document)

    # 実行・検証
    with pytest.raises(SettingsError, match=r"hotkeys\.cancel"):
        load_default_settings(defaults_file, settings_model, os_kind=OsKind.WINDOWS)


# === save_settings ===


def test_save_settings_when_comments(paths: AppPaths, settings_model: type[Settings]) -> None:
    """変えたキーの行だけを書き換え、コメントと空行を保つ（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備
    before = (
        "# 録音まわりのホットキー\n"
        "hotkeys:\n"
        "  # 録音を始めるキー\n"
        f"  start: {HOTKEY_A}\n"
        "\n"
        "# 録音\n"
        "recording:\n"
        "  fade_sec: 1.5\n"
    )
    _write(paths.settings_file, before)
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, _updated(previous, "hotkeys", start=HOTKEY_C))

    # 検証
    assert paths.settings_file.read_text(encoding="utf-8") == before.replace(
        f"start: {HOTKEY_A}", f"start: {HOTKEY_C}"
    )
    assert load_settings(paths, settings_model).hotkeys.start == HOTKEY_C


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        pytest.param(
            "hotkeys:\n"
            f"  start: {HOTKEY_A}\n"
            "  cancel: <ctrl>+<alt>+x  # 取り消しのキー\n"
            "\n"
            "# 録音\n"
            "recording:\n"
            "  fade_sec: 1.5\n",
            {"hotkeys": {"start": HOTKEY_A}, "recording": {"fade_sec": 1.5}},
            id="key",
        ),
        pytest.param(
            "hotkeys:\n"
            "  cancel: <ctrl>+<alt>+x  # 取り消しのキー\n"
            "\n"
            "# 録音\n"
            "recording:\n"
            "  fade_sec: 1.5\n",
            {"recording": {"fade_sec": 1.5}},
            id="table",
        ),
    ],
)
def test_save_settings_when_reset_to_default(
    paths: AppPaths,
    settings_model: type[Settings],
    default_settings: Settings,
    before: str,
    expected: dict[str, Any],
) -> None:
    """既定値と同じ値にしたキーを外し、外したキーの後ろのコメントを残す（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    _write(paths.settings_file, before)
    previous = load_settings(paths, settings_model)
    settings = _updated(previous, "hotkeys", cancel=default_settings.hotkeys.cancel)

    # 実行
    save_settings(paths, previous, settings)

    # 検証
    text = paths.settings_file.read_text(encoding="utf-8")
    assert "cancel" not in text
    assert "# 取り消しのキー" not in text
    assert "# 録音\nrecording:\n" in text
    assert read_yaml_mapping(paths.settings_file) == expected


def test_save_settings_when_added_key(paths: AppPaths, settings_model: type[Settings]) -> None:
    """書いていなかったキーを、次の表の見出しのコメントより前に追加する（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備
    _write(
        paths.settings_file,
        f"hotkeys:\n  start: {HOTKEY_A}\n\n# 録音\nrecording:\n  fade_sec: 1.5\n",
    )
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, _updated(previous, "hotkeys", pause="<ctrl>+<alt>+p"))

    # 検証
    assert paths.settings_file.read_text(encoding="utf-8") == (
        "hotkeys:\n"
        f"  start: {HOTKEY_A}\n"
        "  pause: <ctrl>+<alt>+p\n"
        "\n"
        "# 録音\n"
        "recording:\n"
        "  fade_sec: 1.5\n"
    )


def test_save_settings_when_unchanged_keys(
    paths: AppPaths, settings_model: type[Settings], default_settings: Settings
) -> None:
    """変えていないキーは、既定値と同じでも外さない（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（hotkeys.start を既定値と同じ値で書く）
    _write(paths.settings_file, f"hotkeys:\n  start: {default_settings.hotkeys.start}\n")
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, _updated(previous, "recording", fade_sec=1.5))

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {
        "hotkeys": {"start": default_settings.hotkeys.start},
        "recording": {"fade_sec": 1.5},
    }


def test_save_settings_when_quoted_strings(
    paths: AppPaths,
    settings_model: type[Settings],
    default_settings: Settings,
    make_settings: MakeSettings,
) -> None:
    """YAML 1.1 で文字列でなくなる値を引用符で囲んで書く（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備（`*` だけの文言は検証で断られるため、`*` で始まる文言にする）
    settings = make_settings(
        {"edge_phrases": [{"text": "yes"}, {"text": "on"}, {"text": "*ご視聴"}]}
    )

    # 実行
    save_settings(paths, default_settings, settings)

    # 検証
    text = paths.settings_file.read_text(encoding="utf-8")
    assert "'yes'" in text
    assert "'on'" in text
    assert "'*ご視聴'" in text
    assert [phrase.text for phrase in load_settings(paths, settings_model).edge_phrases] == [
        "yes",
        "on",
        "*ご視聴",
    ]


def test_save_settings_when_restart_item_changed(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """再起動が要る項目が変われば True（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備（large-v3 から small へ変える）
    _write(paths.settings_file, "transcription:\n  local_whisper:\n    model: large-v3\n")
    previous = load_settings(paths, settings_model)
    local_whisper = previous.transcription.local_whisper.model_copy(update={"model": "small"})
    settings = _updated(previous, "transcription", local_whisper=local_whisper)

    # 実行
    restart_required = save_settings(paths, previous, settings)

    # 検証
    assert restart_required is True


def test_save_settings_when_immediate_item_changed(
    paths: AppPaths, default_settings: Settings
) -> None:
    """即時に効く項目だけなら False（正常系）。"""
    from voice_paste.shared.settings import save_settings

    # 実行
    restart_required = save_settings(
        paths, default_settings, _updated(default_settings, "hotkeys", start=HOTKEY_C)
    )

    # 検証
    assert restart_required is False


def test_save_settings_when_missing(
    paths: AppPaths, default_settings: Settings, tmp_path: Path
) -> None:
    """無ければフォルダごと作り、変えたキーだけを書く（正常系）。"""
    import dataclasses

    from voice_paste.shared.settings import save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    missing = dataclasses.replace(paths, settings_file=tmp_path / "not_created" / "settings.yaml")

    # 実行
    restart_required = save_settings(
        missing, default_settings, _updated(default_settings, "hotkeys", start=HOTKEY_C)
    )

    # 検証
    assert restart_required is False
    assert read_yaml_mapping(missing.settings_file) == {"hotkeys": {"start": HOTKEY_C}}


def test_save_settings_when_invalid_existing(paths: AppPaths, default_settings: Settings) -> None:
    """読めない settings.yaml は書き換えずに断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import save_settings

    # 準備
    _write(paths.settings_file, BROKEN_YAML)

    # 実行・検証
    with pytest.raises(SettingsError, match="settings.yaml"):
        save_settings(
            paths, default_settings, _updated(default_settings, "hotkeys", start=HOTKEY_C)
        )
    assert paths.settings_file.read_text(encoding="utf-8") == BROKEN_YAML


def test_save_settings_when_glossary_reset(paths: AppPaths, settings_model: type[Settings]) -> None:
    """用語集の場所を既定（None）に戻すとキーを外す（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    _write(paths.settings_file, "glossary_path: C:/x/yogo.csv\n")
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, previous.model_copy(update={"glossary_path": None}))

    # 検証
    assert "glossary_path" not in read_yaml_mapping(paths.settings_file)
    assert load_settings(paths, settings_model).glossary_path is None


def test_save_settings_when_ai_chat_remains(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """読み替えた設定を保存すると、ai_chat の項目が消えてプリセットとして書かれる（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    _write(paths.settings_file, AI_CHAT_SETTINGS_YAML)
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, _updated(previous, "recording", fade_sec=1.5))

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert "ai_chat" not in [output["id"] for output in written["outputs"]]
    assert [
        (preset["kind"], preset["title"], preset["url"], preset["hotkey"], preset["enabled"])
        for preset in written["presets"]
    ] == [
        ("browser", "ChatGPT", "https://chatgpt.com", "<ctrl>+<alt>+1", True),
        ("browser", "Claude", "https://claude.ai/new", "<ctrl>+<alt>+3", False),
    ]
    assert written["preset_options"]["browser"]["open_delay_sec"] == 2.0


def test_save_settings_when_glossaries(
    paths: AppPaths,
    settings_model: type[Settings],
    default_settings: Settings,
    make_settings: MakeSettings,
    tmp_path: Path,
) -> None:
    """用語集の一覧を書き、設定のフォルダの下の場所は相対パスにする（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（設定のフォルダの下の glossaries/glossary_1.csv と、別のフォルダの絶対パスの 2 件）
    other_path = tmp_path / "other" / "terms.csv"
    settings = make_settings(
        {
            "glossaries": [
                {
                    "name": "yogo",
                    "path": str(paths.settings_file.parent / "glossaries" / "glossary_1.csv"),
                },
                {"name": "会議用", "path": str(other_path)},
            ],
            "active_glossary": "会議用",
        }
    )

    # 実行
    save_settings(paths, default_settings, settings)

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert written["glossaries"][0]["path"] == "glossaries/glossary_1.csv"
    assert Path(written["glossaries"][1]["path"]) == other_path
    loaded = load_settings(paths, settings_model)
    assert [glossary.name for glossary in loaded.glossaries] == ["yogo", "会議用"]
    assert loaded.active_glossary == "会議用"


def test_save_settings_when_glossary_presets(
    paths: AppPaths, settings_model: type[Settings], make_settings: MakeSettings
) -> None:
    """用語集のプリセットを書き、今までの active_glossary のキーを外す（正常系）。"""
    from voice_paste.shared.settings import (
        GlossaryPresetSettings,
        load_settings,
        save_settings,
    )
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（active_glossary を持つ settings.yaml に、active_glossary が None で 2 件の glossary_presets を持つ設定を書く）
    _write(paths.settings_file, "active_glossary: 会議用\n")
    previous = load_settings(paths, settings_model)
    folder = paths.settings_file.parent
    settings = make_settings(
        {
            "glossaries": [
                {"name": "yogo", "path": str(folder / "yogo.csv")},
                {"name": "会議用", "path": str(folder / "meeting.csv")},
            ],
            "active_glossary": None,
            "glossary_presets": [
                {"name": "既定", "glossaries": ["yogo"]},
                {"name": "議事録", "glossaries": ["会議用", "yogo"]},
            ],
            "active_glossary_preset": "議事録",
        }
    )

    # 実行
    save_settings(paths, previous, settings)

    # 検証
    assert "active_glossary" not in read_yaml_mapping(paths.settings_file)
    loaded = load_settings(paths, settings_model)
    assert loaded.glossary_presets == [
        GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
        GlossaryPresetSettings(name="議事録", glossaries=["会議用", "yogo"]),
    ]
    assert loaded.active_glossary_preset == "議事録"


def test_save_settings_when_local_override(paths: AppPaths, settings_model: type[Settings]) -> None:
    """checkout の上書きのファイルは書き換えない（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    assert paths.local_settings_file is not None
    local_text = f"hotkeys:\n  start: {HOTKEY_B}\n"
    _write(paths.local_settings_file, local_text)
    previous = load_settings(paths, settings_model)

    # 実行
    save_settings(paths, previous, _updated(previous, "hotkeys", start=HOTKEY_C))

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {"hotkeys": {"start": HOTKEY_C}}
    assert paths.local_settings_file.read_text(encoding="utf-8") == local_text


# === reset_settings ===


def test_reset_settings(
    paths: AppPaths, settings_model: type[Settings], default_settings: Settings
) -> None:
    """キーを全て外し、先頭のコメントを残す（正常系）。"""
    from voice_paste.shared.settings import load_settings, reset_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（先頭のコメントと 3 つの表）
    _write(
        paths.settings_file,
        "# 手元の設定\n"
        "hotkeys:\n"
        f"  start: {HOTKEY_A}\n"
        "recording:\n"
        "  fade_sec: 1.5\n"
        "ui:\n"
        "  show_hotkeys: false\n",
    )

    # 実行
    reset_settings(paths.settings_file)

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {}
    assert "# 手元の設定" in paths.settings_file.read_text(encoding="utf-8")
    assert load_settings(paths, settings_model) == default_settings


def test_reset_settings_when_missing(paths: AppPaths) -> None:
    """無ければ作らない（正常系）。"""
    from voice_paste.shared.settings import reset_settings

    # 実行
    reset_settings(paths.settings_file)

    # 検証
    assert not paths.settings_file.exists()


# === migrate_settings_toml ===


def test_migrate_settings_toml(paths: AppPaths) -> None:
    """既定値と違うキーだけを移し、既定値に重ねると TOML の値と等しい（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, migrate_settings_toml
    from voice_paste.shared.yaml_document import merge_layers, read_yaml_mapping

    # 準備（hotkeys.start と transcription.engine を既定と違う値にし、他のキーを既定値で全て書く）
    defaults = _read_defaults(DEFAULTS_FILE)
    values = copy.deepcopy(defaults)
    values["hotkeys"]["start"] = HOTKEY_B
    values["transcription"]["engine"] = "openai"
    toml_text = _write_toml(paths.legacy_settings_file, values)

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert written == {"hotkeys": {"start": HOTKEY_B}, "transcription": {"engine": "openai"}}
    assert merge_layers(defaults, written) == values
    assert paths.legacy_settings_file.read_text(encoding="utf-8") == toml_text


def test_migrate_settings_toml_when_lists(paths: AppPaths) -> None:
    """一覧は一部だけ違っても丸ごと移す（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, migrate_settings_toml
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（edge_phrases の 1 行だけを既定と違う値にする）
    defaults = _read_defaults(DEFAULTS_FILE)
    phrases = copy.deepcopy(defaults["edge_phrases"])
    phrases[0]["text"] = "字幕*"
    _write_toml(paths.legacy_settings_file, {"edge_phrases": phrases})

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {"edge_phrases": phrases}


def test_migrate_settings_toml_when_special_strings(paths: AppPaths) -> None:
    """YAML で特別な意味を持つ文字列を文字列のまま移す（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, migrate_settings_toml
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    defaults = _read_defaults(DEFAULTS_FILE)
    phrases = [{"text": text, "position": "end"} for text in SPECIAL_STRINGS]
    _write_toml(paths.legacy_settings_file, {"edge_phrases": phrases})

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    assert read_yaml_mapping(paths.settings_file)["edge_phrases"] == phrases


def test_migrate_settings_toml_when_ai_chat_remains(paths: AppPaths) -> None:
    """古い AI チャットの設定はプリセットに読み替えて移す（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, migrate_settings_toml
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（既定の出力先の一覧の後ろに ai_chat を書く）
    defaults = _read_defaults(DEFAULTS_FILE)
    ai_chat = {
        "id": "ai_chat",
        "targets": [
            {
                "name": "ChatGPT",
                "url": "https://chatgpt.com",
                "hotkey": "<ctrl>+<alt>+1",
                "enabled": True,
            }
        ],
    }
    _write_toml(paths.legacy_settings_file, {"outputs": [*defaults["outputs"], ai_chat]})

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert "ai_chat" not in [output["id"] for output in written.get("outputs", [])]
    assert written["presets"] == [
        {
            "kind": "browser",
            "title": "ChatGPT",
            "url": "https://chatgpt.com",
            "hotkey": "<ctrl>+<alt>+1",
            "enabled": True,
            "send_enter": True,
        }
    ]


def test_migrate_settings_toml_when_only_show_hotkeys(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """録音の画面のホットキーの表示だけが既定と違えば、文字起こし中の表示も同じ値で移す（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, load_settings, migrate_settings_toml
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    defaults = _read_defaults(DEFAULTS_FILE)
    _write(paths.legacy_settings_file, "[ui]\nshow_hotkeys = false\n")

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {
        "ui": {"show_hotkeys": False, "transcribing_show_hotkeys": False}
    }
    assert load_settings(paths, settings_model).ui.transcribing_show_hotkeys is False


def test_migrate_settings_toml_when_transcribing_show_hotkeys_default(
    paths: AppPaths, settings_model: type[Settings]
) -> None:
    """文字起こし中の表示が既定値と同じなら外して移し、読み直しても既定値のまま（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, load_settings, migrate_settings_toml
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    defaults = _read_defaults(DEFAULTS_FILE)
    _write(
        paths.legacy_settings_file,
        "[ui]\nshow_hotkeys = false\ntranscribing_show_hotkeys = true\n",
    )

    # 実行
    migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 検証
    assert read_yaml_mapping(paths.settings_file) == {"ui": {"show_hotkeys": False}}
    assert load_settings(paths, settings_model).ui.transcribing_show_hotkeys is True


# === inherit_transcribing_show_hotkeys ===


def test_inherit_transcribing_show_hotkeys_when_missing() -> None:
    """文字起こし中の表示の項目が無ければ録音の画面の値を入れる（正常系）。"""
    from voice_paste.shared.settings import inherit_transcribing_show_hotkeys

    # 準備
    layer: dict[str, Any] = {"ui": {"show_hotkeys": False}}

    # 実行
    inherited = inherit_transcribing_show_hotkeys(layer)

    # 検証
    assert inherited == {"ui": {"show_hotkeys": False, "transcribing_show_hotkeys": False}}
    assert layer == {"ui": {"show_hotkeys": False}}


@pytest.mark.parametrize(
    "layer",
    [pytest.param({}, id="empty"), pytest.param({"ui": {"theme": "dark"}}, id="other_key")],
)
def test_inherit_transcribing_show_hotkeys_when_both_missing(layer: dict[str, Any]) -> None:
    """どちらの項目も無ければそのまま返す（正常系）。"""
    from voice_paste.shared.settings import inherit_transcribing_show_hotkeys

    # 準備
    expected = copy.deepcopy(layer)

    # 実行
    inherited = inherit_transcribing_show_hotkeys(layer)

    # 検証
    assert inherited == expected


def test_inherit_transcribing_show_hotkeys_when_set() -> None:
    """文字起こし中の表示の項目があればその値を保つ（正常系）。"""
    from voice_paste.shared.settings import inherit_transcribing_show_hotkeys

    # 準備
    layer: dict[str, Any] = {"ui": {"show_hotkeys": False, "transcribing_show_hotkeys": True}}

    # 実行
    inherited = inherit_transcribing_show_hotkeys(layer)

    # 検証
    assert inherited["ui"]["transcribing_show_hotkeys"] is True


# === find_hotkey_overlaps ===


def test_find_hotkey_overlaps(default_settings: Settings) -> None:
    """前に並んだホットキーと重なるキーを、重なった組で返す（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.shared.settings import BrowserPreset, find_hotkey_overlaps

    # 準備: 2 件目のプリセットの hotkey を、貼り付けのみと同じにする（確かめを飛ばして作る）
    settings = default_settings.model_copy(
        update={
            "outputs": [
                PasteAndSendSettings(hotkey="<ctrl>+<alt>+d"),
                PasteOnlySettings(hotkey="<ctrl>+<alt>+v"),
                CopyOnlySettings(hotkey="<ctrl>+<alt>+c"),
            ],
            "presets": [
                BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1"),
                BrowserPreset(title="Claude", url="https://claude.ai/new", hotkey="<ctrl>+<alt>+v"),
            ],
        }
    )

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == [("presets[1].hotkey", "outputs[1].hotkey")]


def test_find_hotkey_overlaps_when_presets_of_different_kinds(default_settings: Settings) -> None:
    """種類をまたいだプリセットどうしの重なりを返す（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset, EndpointPreset, find_hotkey_overlaps

    # 準備
    settings = default_settings.model_copy(
        update={
            "presets": [
                BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+3"),
                EndpointPreset(
                    title="受信先", url="http://127.0.0.1:9000/hook", hotkey="<ctrl>+<alt>+3"
                ),
            ]
        }
    )

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == [("presets[1].hotkey", "presets[0].hotkey")]


def test_find_hotkey_overlaps_when_start_equals_paste_and_send(
    default_settings: Settings,
) -> None:
    """録音の開始と貼り付けて送信が同じキー（既定）は重なりにしない（正常系）。"""
    from voice_paste.shared.settings import find_hotkey_overlaps

    # 実行
    overlaps = find_hotkey_overlaps(default_settings)

    # 検証
    assert overlaps == []


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            {
                "outputs": [
                    {"id": "paste_and_send", "hotkey": "<ctrl>+<alt>+d"},
                    {"id": "paste_only", "hotkey": "<ctrl>+<alt>+v"},
                    {"id": "copy_only", "enabled": False, "hotkey": "<ctrl>+<alt>+z"},
                ]
            },
            id="disabled_output",
        ),
        pytest.param(
            {
                "presets": [
                    {
                        "kind": "browser",
                        "title": "ChatGPT",
                        "url": "https://chatgpt.com",
                        "hotkey": "<ctrl>+<alt>+z",
                        "enabled": False,
                    }
                ]
            },
            id="disabled_preset",
        ),
    ],
)
def test_find_hotkey_overlaps_when_disabled_output(
    make_settings: MakeSettings, document: dict[str, object]
) -> None:
    """オフの出力先・無効のプリセットのホットキーは重なりにしない（正常系）。"""
    from voice_paste.shared.settings import find_hotkey_overlaps

    # 準備: ホットキーを一時停止と同じ <ctrl>+<alt>+z にしたものをオフ・無効にする
    settings = make_settings(document)

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == []


def test_find_hotkey_overlaps_when_empty_preset_hotkeys(default_settings: Settings) -> None:
    """空のホットキーのプリセットどうしは重なりにしない（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset, find_hotkey_overlaps

    # 準備
    settings = default_settings.model_copy(
        update={
            "presets": [
                BrowserPreset(title="ChatGPT", url="https://chatgpt.com"),
                BrowserPreset(title="Claude", url="https://claude.ai/new"),
            ]
        }
    )

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == []


# === migrate_ai_chat ===

AI_CHAT_DOCUMENT = {
    "outputs": [
        {"id": "paste_and_send"},
        {
            "id": "ai_chat",
            "open_delay_sec": 2.0,
            "targets": [
                {
                    "name": "ChatGPT",
                    "url": "https://chatgpt.com",
                    "hotkey": "<ctrl>+<alt>+1",
                    "enabled": True,
                },
                {
                    "name": "Claude",
                    "url": "https://claude.ai/new",
                    "hotkey": "<ctrl>+<alt>+3",
                    "enabled": False,
                },
            ],
        },
    ]
}
"""古い AI チャットの設定（送信先 2 件、開くまでの間 2.0 秒）を持つ設定を素の dict にしたもの。"""


def test_migrate_ai_chat() -> None:
    """送信先をブラウザ添付のプリセットにし、ai_chat を外す（正常系）。"""
    import copy

    from voice_paste.shared.settings import migrate_ai_chat

    # 準備
    document = copy.deepcopy(AI_CHAT_DOCUMENT)

    # 実行
    migrated = migrate_ai_chat(document)

    # 検証
    assert migrated["outputs"] == [{"id": "paste_and_send"}]
    assert migrated["presets"] == [
        {
            "kind": "browser",
            "title": "ChatGPT",
            "url": "https://chatgpt.com",
            "hotkey": "<ctrl>+<alt>+1",
            "enabled": True,
            "send_enter": True,
        },
        {
            "kind": "browser",
            "title": "Claude",
            "url": "https://claude.ai/new",
            "hotkey": "<ctrl>+<alt>+3",
            "enabled": False,
            "send_enter": True,
        },
    ]
    assert migrated["preset_options"]["browser"]["open_delay_sec"] == 2.0
    assert document == AI_CHAT_DOCUMENT


def test_migrate_ai_chat_when_output_disabled() -> None:
    """オフの AI チャットの送信先は無効のプリセットにする（正常系）。"""
    from voice_paste.shared.settings import migrate_ai_chat

    # 準備
    document = {
        "outputs": [
            {
                "id": "ai_chat",
                "enabled": False,
                "targets": [
                    {
                        "name": "ChatGPT",
                        "url": "https://chatgpt.com",
                        "hotkey": "<ctrl>+<alt>+1",
                        "enabled": True,
                    },
                    {
                        "name": "Claude",
                        "url": "https://claude.ai/new",
                        "hotkey": "<ctrl>+<alt>+3",
                        "enabled": True,
                    },
                ],
            }
        ]
    }

    # 実行
    migrated = migrate_ai_chat(document)

    # 検証
    assert [preset["enabled"] for preset in migrated["presets"]] == [False, False]


def test_migrate_ai_chat_when_targets_missing() -> None:
    """targets の無い ai_chat は前の既定の 3 件をプリセットにする（正常系）。"""
    from voice_paste.shared.settings import migrate_ai_chat

    # 準備
    document = {"outputs": [{"id": "ai_chat"}]}

    # 実行
    migrated = migrate_ai_chat(document)

    # 検証
    assert [(preset["title"], preset["hotkey"]) for preset in migrated["presets"]] == [
        ("ChatGPT", "<ctrl>+<alt>+1"),
        ("Google AI", "<ctrl>+<alt>+2"),
        ("Claude", "<ctrl>+<alt>+3"),
    ]


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"outputs": [{"id": "paste_only"}]}, id="without_ai_chat"),
        pytest.param({}, id="without_outputs"),
    ],
)
def test_migrate_ai_chat_when_absent(document: dict[str, object]) -> None:
    """ai_chat が無ければ変えない（正常系）。"""
    from voice_paste.shared.settings import migrate_ai_chat

    # 実行
    migrated = migrate_ai_chat(document)

    # 検証
    assert migrated == document


# === Settings の確かめ ===


def test_settings_when_hotkeys_overlap(settings_model: type[Settings]) -> None:
    """ホットキーが重なる設定は、重なったキーと先のキーを持つ ValidationError で断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"hotkeys": {"pause": "<ctrl>+<alt>+z", "cancel": "<ctrl>+<alt>+z"}})
        )
    failures = list_validation_failures(exc_info.value)
    assert len(failures) == 1
    key, reason = failures[0]
    assert key == "hotkeys.cancel"
    assert "hotkeys.pause" in reason


# === ApiSettings の確かめ（_origins_must_be_origin_form） ===


def test_api_settings_when_web_origin_form(make_settings: MakeSettings) -> None:
    """形式の合う Origin を通す（正常系）。"""
    # 準備
    origins = ["https://voice.example.com", "http://localhost:47823"]

    # 実行
    api = make_settings({"api": {"allowed_web_origins": origins}}).api

    # 検証
    assert api.allowed_web_origins == ["https://voice.example.com", "http://localhost:47823"]


def test_api_settings_when_web_origin_not_form(settings_model: type[Settings]) -> None:
    """形式の違う Origin を断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import WEB_ORIGIN_FORM_ERROR_TYPE

    # 準備
    origins = ["https://voice.example.com/", "https://ok.example.com", "voice.example.com"]

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(make_test_document({"api": {"allowed_web_origins": origins}}))
    errors = exc_info.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [
        (WEB_ORIGIN_FORM_ERROR_TYPE, ("api", "allowed_web_origins"))
    ]
    assert errors[0]["ctx"]["invalid"] == ("https://voice.example.com/", "voice.example.com")


# === find_glossary_name_overlaps ===


def test_find_glossary_name_overlaps() -> None:
    """後ろにある側を重なりとして返す（正常系）。"""
    from voice_paste.shared.settings import (
        GlossarySettings,
        Settings,
        find_glossary_name_overlaps,
    )

    # 準備（名前が「yogo」「会議用」「会議用」の 3 件。確かめを飛ばして作る）
    settings = Settings.model_construct(
        glossaries=[
            GlossarySettings(name="yogo", path=Path("a.csv")),
            GlossarySettings(name="会議用", path=Path("b.csv")),
            GlossarySettings(name="会議用", path=Path("c.csv")),
        ]
    )

    # 実行
    overlaps = find_glossary_name_overlaps(settings)

    # 検証
    assert overlaps == [("glossaries[2].name", "会議用")]


def test_find_glossary_name_overlaps_when_unique() -> None:
    """重なりが無ければ空（正常系）。"""
    from voice_paste.shared.settings import (
        GlossarySettings,
        Settings,
        find_glossary_name_overlaps,
    )

    # 準備（名前が全て違う 2 件）
    settings = Settings.model_construct(
        glossaries=[
            GlossarySettings(name="yogo", path=Path("a.csv")),
            GlossarySettings(name="会議用", path=Path("b.csv")),
        ]
    )

    # 実行
    overlaps = find_glossary_name_overlaps(settings)

    # 検証
    assert overlaps == []


def test_settings_when_glossary_names_overlap(settings_model: type[Settings]) -> None:
    """名前が重なる設定は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が同じ 2 件の glossaries）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {
                    "glossaries": [
                        {"name": "会議用", "path": "a.csv"},
                        {"name": "会議用", "path": "b.csv"},
                    ]
                }
            )
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossaries[1].name"]


def test_settings_when_glossary_name_blank(settings_model: type[Settings]) -> None:
    """空白だけの名前は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が「  」の glossaries）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"glossaries": [{"name": "  ", "path": "a.csv"}]})
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossaries[0].name"]


# === find_glossary_preset_name_overlaps ===


def test_find_glossary_preset_name_overlaps() -> None:
    """後ろにある側を重なりとして返す（正常系）。"""
    from voice_paste.shared.settings import (
        GlossaryPresetSettings,
        Settings,
        find_glossary_preset_name_overlaps,
    )

    # 準備（名前が「既定」「会議」「既定」の 3 件。確かめを飛ばして作る）
    settings = Settings.model_construct(
        glossary_presets=[
            GlossaryPresetSettings(name="既定"),
            GlossaryPresetSettings(name="会議"),
            GlossaryPresetSettings(name="既定"),
        ]
    )

    # 実行
    overlaps = find_glossary_preset_name_overlaps(settings)

    # 検証
    assert overlaps == [("glossary_presets[2].name", "既定")]


def test_settings_when_glossary_preset_names_overlap(settings_model: type[Settings]) -> None:
    """名前が重なる設定は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import (
        GLOSSARY_PRESET_NAME_OVERLAP_ERROR_TYPE,
        list_validation_failures,
    )

    # 実行・検証（名前が同じ 2 件の glossary_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {
                    "glossary_presets": [
                        {"name": "既定", "glossaries": []},
                        {"name": "既定", "glossaries": []},
                    ]
                }
            )
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossary_presets[1].name"]
    assert [error["type"] for error in exc_info.value.errors()] == [
        GLOSSARY_PRESET_NAME_OVERLAP_ERROR_TYPE
    ]
    assert GLOSSARY_PRESET_NAME_OVERLAP_ERROR_TYPE == "glossary_preset_name_overlap"


def test_settings_when_glossary_preset_name_blank(settings_model: type[Settings]) -> None:
    """空白だけの名前は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が「  」の glossary_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"glossary_presets": [{"name": "  ", "glossaries": []}]})
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossary_presets[0].name"]


def test_settings_when_glossary_preset_glossaries_duplicated(
    settings_model: type[Settings],
) -> None:
    """1 つのプリセットに同じ用語集を 2 回並べた設定は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（glossaries が ["yogo", "yogo"] の glossary_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {"glossary_presets": [{"name": "既定", "glossaries": ["yogo", "yogo"]}]}
            )
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossary_presets[0].glossaries"]


# === EdgePhraseSettings ===


def test_edge_phrase_settings() -> None:
    """文言と位置を読む（正常系）。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    # 実行（前後に空白のある文言で、位置は無し）
    phrase = EdgePhraseSettings(text=" ご視聴ありがとうございました ")

    # 検証
    assert phrase.text == "ご視聴ありがとうございました"
    assert phrase.position == "end"


def test_edge_phrase_settings_when_wildcard_only(settings_model: type[Settings]) -> None:
    """`*` だけの文言を断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE

    # 実行・検証（edge_phrases の 2 件目の text が「 * 」）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {"edge_phrases": [{"text": "字幕*"}, {"text": " * ", "position": "start"}]}
            )
        )
    errors = exc_info.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [
        (EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE, ("edge_phrases", 1, "text"))
    ]


# === join_hint_words ===

HINT_LIMIT_BYTES = 222
"""表記のヒントの長さの上限（UTF-8 のバイト数）。"""

JAPANESE_CHAR_BYTES = 3
"""日本語 1 文字の UTF-8 のバイト数。"""


def _hint_preset(name: str, words: list[str], *, enabled: bool = True) -> dict[str, Any]:
    """設定と同じ構造の表記のヒントのプリセット 1 件を返す。"""
    return {"name": name, "words": words, "enabled": enabled}


def test_join_hint_words() -> None:
    """有効なプリセットの語を一覧の順につなぐ（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings, join_hint_words

    # 準備（有効な A・無効な B・有効な C）
    presets = [
        HintPresetSettings(name="A", words=["voice-paste", "Whisper"]),
        HintPresetSettings(name="B", words=["議事録"], enabled=False),
        HintPresetSettings(name="C", words=["返信"]),
    ]

    # 実行
    hint = join_hint_words(presets)

    # 検証
    assert hint == "voice-paste、Whisper、返信"


@pytest.mark.parametrize(
    "presets",
    [
        pytest.param([], id="empty"),
        pytest.param([_hint_preset("A", ["voice-paste"], enabled=False)], id="all-disabled"),
    ],
)
def test_join_hint_words_when_none_enabled(presets: list[dict[str, Any]]) -> None:
    """有効な語が無ければ空文字を返す（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings, join_hint_words

    # 準備
    hint_presets = [HintPresetSettings(**preset) for preset in presets]

    # 実行
    hint = join_hint_words(hint_presets)

    # 検証
    assert hint == ""


def test_join_hint_words_when_unvalidated() -> None:
    """確かめを通らない値もそのままつなぐ（正常系）。"""
    from types import SimpleNamespace

    from voice_paste.shared.settings import join_hint_words

    # 準備（HintPresetSettings でない、空の語と区切りを含む語を持つ値）
    presets = [SimpleNamespace(enabled=True, words=["", "A、B"])]

    # 実行
    hint = join_hint_words(presets)

    # 検証
    assert hint == "、A、B"


def test_settings_when_hint_at_limit(settings_model: type[Settings]) -> None:
    """つないだ長さが上限ちょうどなら通る（正常系）。"""
    # 準備（日本語 74 文字 = 222 バイト）
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES)

    # 実行
    settings = settings_model.model_validate(
        make_test_document({"hint_presets": [_hint_preset("開発", [word])]})
    )

    # 検証
    assert len(settings.hint_presets[0].words[0].encode("utf-8")) == HINT_LIMIT_BYTES


def test_settings_when_hint_too_long(settings_model: type[Settings]) -> None:
    """上限を 1 バイトでも超えたら通らない（異常系）。"""
    from pydantic import ValidationError

    # 準備（1 バイトの英字 + 日本語 74 文字 = 223 バイト）
    word = "a" + "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES)

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"hint_presets": [_hint_preset("開発", [word])]})
        )
    errors = exc_info.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [
        ("hint_too_long", ("hint_presets",))
    ]


def test_settings_when_disabled_hint_long(settings_model: type[Settings]) -> None:
    """無効のプリセットの語は長さに数えない（正常系）。"""
    # 準備（有効な語は 100 バイト、無効なプリセットは 300 バイトの語）
    presets = [
        _hint_preset("開発", ["a" * 100]),
        _hint_preset("会議", ["あ" * 100], enabled=False),
    ]

    # 実行
    settings = settings_model.model_validate(make_test_document({"hint_presets": presets}))

    # 検証
    assert [preset.enabled for preset in settings.hint_presets] == [True, False]


def test_settings_when_hint_word_has_separator(settings_model: type[Settings]) -> None:
    """読点・句点・改行を含む語は通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 準備（語「A、B」「C。」「D\nE」をそれぞれ持つ無効のプリセット）
    presets = [
        _hint_preset("一", ["A、B"], enabled=False),
        _hint_preset("二", ["C。"], enabled=False),
        _hint_preset("三", ["D\nE"], enabled=False),
    ]

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(make_test_document({"hint_presets": presets}))
    assert {error["type"] for error in exc_info.value.errors()} == {"hint_word_separator"}
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == [
        "hint_presets[0].words[0]",
        "hint_presets[1].words[0]",
        "hint_presets[2].words[0]",
    ]


def test_settings_when_hint_word_blank(settings_model: type[Settings]) -> None:
    """空白だけの語は通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（語「  」の hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"hint_presets": [_hint_preset("開発", ["  "])]})
        )
    assert [error["type"] for error in exc_info.value.errors()] == ["hint_word_empty"]
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["hint_presets[0].words[0]"]


# === find_hint_preset_name_overlaps ===


def test_find_hint_preset_name_overlaps() -> None:
    """後ろにある側を重なりとして返す（正常系）。"""
    from voice_paste.shared.settings import (
        HintPresetSettings,
        Settings,
        find_hint_preset_name_overlaps,
    )

    # 準備（名前が「開発」「会議」「開発」の 3 件。確かめを飛ばして作る）
    settings = Settings.model_construct(
        hint_presets=[
            HintPresetSettings(name="開発"),
            HintPresetSettings(name="会議"),
            HintPresetSettings(name="開発"),
        ]
    )

    # 実行
    overlaps = find_hint_preset_name_overlaps(settings)

    # 検証
    assert overlaps == [("hint_presets[2].name", "開発")]


def test_settings_when_hint_preset_names_overlap(settings_model: type[Settings]) -> None:
    """名前が重なる設定は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が同じ 2 件の hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {"hint_presets": [_hint_preset("開発", ["A"]), _hint_preset("開発", ["B"])]}
            )
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["hint_presets[1].name"]


def test_settings_when_hint_preset_name_blank(settings_model: type[Settings]) -> None:
    """空白だけの名前は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が「  」の hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"hint_presets": [_hint_preset("  ", ["A"])]})
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["hint_presets[0].name"]


# === build_settings_model ===


def _output_model(output_id: str, *, delay_sec: float | None = None) -> type[OutputSettingsBase]:
    """ID が output_id の試しの出力先のモデルを作る。delay_sec を渡すと、その既定値の delay_sec の項目を持つ。"""
    from pydantic import create_model

    from voice_paste.shared.settings import OutputSettingsBase as OutputSettingsBaseModel

    fields: dict[str, Any] = {
        "id": (Literal[output_id], output_id),
        "hotkey": (str, f"<ctrl>+<alt>+{output_id}"),
    }
    if delay_sec is not None:
        fields["delay_sec"] = (float, delay_sec)
    return create_model(f"Output_{output_id}", __base__=OutputSettingsBaseModel, **fields)


def test_build_settings_model() -> None:
    """渡したモデルで outputs を検証する（正常系）。"""
    from voice_paste.shared.settings import _read_defaults, build_settings_model

    # 準備
    model_a = _output_model("a")
    model_b = _output_model("b", delay_sec=1.0)
    model = build_settings_model([model_a, model_b])
    document = _read_defaults(DEFAULTS_FILE)
    document["outputs"] = [{"id": "b", "hotkey": "<ctrl>+<alt>+b", "delay_sec": 2.0}]

    # 実行
    validated = model.model_validate(document)

    # 検証
    assert type(validated.outputs[0]) is model_b
    assert validated.outputs[0].delay_sec == 2.0
    assert validated.model_dump(mode="json")["outputs"][0]["delay_sec"] == 2.0
    assert model.output_models == {"a": model_a, "b": model_b}


def test_build_settings_model_when_unknown_output() -> None:
    """渡していない出力先の ID を断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import (
        _read_defaults,
        build_settings_model,
        list_validation_failures,
    )

    # 準備
    model = build_settings_model([_output_model("a"), _output_model("b")])
    document = _read_defaults(DEFAULTS_FILE)
    document["outputs"] = [{"id": "c"}]

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(document)
    keys = [key for key, _reason in list_validation_failures(exc_info.value)]
    assert keys != []
    assert all(key.startswith("outputs[0]") for key in keys)


def test_build_settings_model_when_single_output() -> None:
    """出力先が 1 つでも組み立てられる（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import (
        _read_defaults,
        build_settings_model,
        list_validation_failures,
    )

    # 準備（hotkey が文字列でない）
    model = build_settings_model([_output_model("a")])
    document = _read_defaults(DEFAULTS_FILE)
    document["outputs"] = [{"id": "a", "hotkey": 1}]

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(document)
    assert [key for key, _reason in list_validation_failures(exc_info.value)] == [
        "outputs[0].hotkey"
    ]


def test_build_settings_model_when_duplicate_id() -> None:
    """ID が重なる登録を断る（異常系）。"""
    from voice_paste.shared.settings import build_settings_model

    # 準備
    models = [_output_model("dup_id"), _output_model("dup_id")]

    # 実行・検証
    with pytest.raises(ValueError, match="dup_id"):
        build_settings_model(models)


# === Haas と表記のヒントの読み ===


def test_collect_hint_vocabulary() -> None:
    """有効なプリセットの語を表記と読みの組で返す（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings, collect_hint_vocabulary

    # 準備
    presets = [
        HintPresetSettings(name="A", words=["突合", "voice-paste"], readings=["とつごう", ""]),
        HintPresetSettings(name="B", words=["議事録"], enabled=False),
    ]

    # 実行
    words = collect_hint_vocabulary(presets)

    # 検証
    assert words == [("突合", "とつごう"), ("voice-paste", None)]


def test_collect_hint_vocabulary_when_no_readings() -> None:
    """readings が空の一覧なら読みは全て None（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings, collect_hint_vocabulary

    # 実行
    words = collect_hint_vocabulary([HintPresetSettings(name="A", words=["A", "B"])])

    # 検証
    assert words == [("A", None), ("B", None)]


def test_collect_hint_vocabulary_when_duplicate_word() -> None:
    """同じ表記は 1 つにまとめ、読みのある方を残す（正常系）。"""
    from voice_paste.shared.settings import HintPresetSettings, collect_hint_vocabulary

    # 準備
    presets = [
        HintPresetSettings(name="A", words=["突合"], readings=[""]),
        HintPresetSettings(name="B", words=["突合"], readings=["とつごう"]),
    ]

    # 実行
    words = collect_hint_vocabulary(presets)

    # 検証
    assert words == [("突合", "とつごう")]


def _hint_document(words: list[str], readings: list[str]) -> dict[str, Any]:
    """語と読みを持つプリセットが 1 つの設定の値を作る。"""
    return make_test_document({"hint_presets": [{"name": "A", "words": words, "readings": readings}]})


def test_settings_when_hint_reading_not_kana(settings_model: type[Settings]) -> None:
    """読みにかな以外の文字が入っていたら断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(_hint_document(["突合"], ["totsugou"]))
    error = exc_info.value.errors()[0]
    assert error["type"] == "hint_reading_not_kana"
    assert error["loc"] == ("hint_presets", 0, "readings", 0)


def test_settings_when_hint_readings_length(settings_model: type[Settings]) -> None:
    """読みの数が語の数と違えば断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(_hint_document(["A", "B"], ["あ"]))
    error = exc_info.value.errors()[0]
    assert error["type"] == "hint_readings_length"
    assert error["loc"] == ("hint_presets", 0, "readings")


def test_settings_when_hint_reading_conflict(settings_model: type[Settings]) -> None:
    """同じ語に違う読みがあれば、後ろの語の読みの場所で断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(_hint_document(["突合", "突合"], ["とつごう", "とつあわせ"]))
    error = exc_info.value.errors()[0]
    assert error["type"] == "hint_reading_conflict"
    assert error["loc"] == ("hint_presets", 0, "readings", 1)


def test_settings_when_hint_reading_blank_on_duplicate_word(settings_model: type[Settings]) -> None:
    """同じ語で片方の読みが空なら通る（正常系）。"""
    # 実行
    settings = settings_model.model_validate(_hint_document(["突合", "突合"], ["とつごう", ""]))

    # 検証
    assert settings.hint_presets[0].readings == ["とつごう", ""]


def test_settings_when_haas_port_overlap(settings_model: type[Settings]) -> None:
    """Haas のポートが API のポートと同じなら断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document(
                {"api": {"port": 47900}, "transcription": {"haas": {"port": 47900}}}
            )
        )
    error = exc_info.value.errors()[0]
    assert error["type"] == "haas_port_overlap"
    assert error["loc"] == ("transcription", "haas", "port")


def test_settings_when_haas_model_empty(settings_model: type[Settings]) -> None:
    """Haas のモデルが空白だけなら断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(make_test_document({"transcription": {"haas": {"model": "  "}}}))
    error = exc_info.value.errors()[0]
    assert error["type"] == "haas_model_empty"
    assert error["loc"] == ("transcription", "haas", "model")


def test_settings_when_haas_device_invalid(settings_model: type[Settings]) -> None:
    """Haas の装置の形式が違えば断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(make_test_document({"transcription": {"haas": {"device": "gpu"}}}))
    error = exc_info.value.errors()[0]
    assert error["type"] == "haas_device_form"
    assert error["loc"] == ("transcription", "haas", "device")


def test_settings_when_haas_device_numbered(settings_model: type[Settings]) -> None:
    """番号つきの cuda は通る（正常系）。"""
    # 実行
    settings = settings_model.model_validate(
        make_test_document({"transcription": {"haas": {"device": "cuda:1"}}})
    )

    # 検証
    assert settings.transcription.haas.device == "cuda:1"


def test_settings_when_haas_separator_too_long(settings_model: type[Settings]) -> None:
    """Haas の区切りをつなぐ文字が 16 文字を超えれば断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            make_test_document({"transcription": {"haas": {"separator": "あ" * 17}}})
        )
    error = exc_info.value.errors()[0]
    assert error["type"] == "haas_separator_too_long"
    assert error["loc"] == ("transcription", "haas", "separator")


def test_settings_when_haas_out_of_range(settings_model: type[Settings]) -> None:
    """Haas の数値が範囲の外なら断る（異常系）。"""
    from pydantic import ValidationError

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(make_test_document({"transcription": {"haas": {"chunk_sec": 0.5}}}))
    error = exc_info.value.errors()[0]
    assert error["loc"] == ("transcription", "haas", "chunk_sec")
