"""shared/settings.py（load_settings・save_settings・find_hotkey_overlaps・find_glossary_name_overlaps・find_glossary_preset_name_overlaps・join_hint_words・find_hint_preset_name_overlaps・EdgePhraseSettings・migrate_ai_chat・build_settings_model・Settings の確かめ・UiSettings の確かめ）の単体テスト。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from voice_paste.shared.settings import OutputSettingsBase, Settings

SETTINGS_FILE_NAME = "settings.toml"

COMMON_DEFAULTS = {
    "recording.lower_volume": True,
    "transcription.local_whisper.device": "cuda",
    "transcription.local_whisper.compute_type": "float16",
    "hotkeys.start": "<ctrl>+<alt>+d",
    "hotkeys.pause": "<ctrl>+<alt>+z",
    "hotkeys.cancel": "<ctrl>+<alt>+q",
    "outputs.paste_and_send.hotkey": "<ctrl>+<alt>+d",
    "outputs.paste_only.hotkey": "<ctrl>+<alt>+v",
    "outputs.copy_only.hotkey": "<ctrl>+<alt>+c",
}
"""OS ごとに既定値を上書きする設定のキーの、共通の既定値（Windows の値）。見本はこの値で書く。"""

COMMENT_AFTER_ARRAY_TABLE = "# 保存しても残るコメント"
"""配列の表（`[[hint_presets]]`）の後ろに書いておく、キーを持たないコメント。"""

HINT_PRESET_A = '[[hint_presets]]\nname = "A"\nwords = ["a"]\nenabled = true\n'
"""settings.toml に書く表記のヒントのプリセット A。"""

HINT_PRESET_B = '[[hint_presets]]\nname = "B"\nwords = ["b"]\nenabled = true\n'
"""settings.toml に書く表記のヒントのプリセット B。"""

LINUX_DEFAULTS = {
    "recording.lower_volume": False,
    "transcription.local_whisper.device": "cpu",
    "transcription.local_whisper.compute_type": "int8",
    "hotkeys.start": "<cmd>+<alt>+d",
    "hotkeys.pause": "<cmd>+<alt>+z",
    "hotkeys.cancel": "<cmd>+<alt>+q",
    "outputs.paste_and_send.hotkey": "<cmd>+<alt>+d",
    "outputs.paste_only.hotkey": "<cmd>+<alt>+v",
    "outputs.copy_only.hotkey": "<cmd>+<alt>+c",
}
"""Linux の既定値が共通の既定値と変わる設定のキーと、その Linux の値。"""

LINUX_SETTINGS_MODEL_SCRIPT = """
import json

import voice_paste.shared.os_kind as os_kind

os_kind.CURRENT_OS = os_kind.OsKind.LINUX

from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import OS_DEFAULT_OVERRIDES

print(
    json.dumps(
        {
            "defaults": SETTINGS_MODEL().model_dump(mode="json"),
            "overrides": OS_DEFAULT_OVERRIDES[os_kind.OsKind.LINUX],
        }
    )
)
"""
"""子プロセスで CURRENT_OS を Linux にしてから main を import し、組み立てた設定のモデルの既定値と Linux の上書きを JSON で出すスクリプト。"""


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """一時フォルダの settings.toml のパスを返す（ファイルはまだ無い）。"""
    return tmp_path / SETTINGS_FILE_NAME


# === load_settings ===


def test_load_settings_when_missing(settings_file: Path, settings_model: type[Settings]) -> None:
    """無ければ既定値で作る（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 実行
    settings = load_settings(settings_file, settings_model)

    # 検証
    assert settings == settings_model()
    assert settings_file.exists()


def test_load_settings(settings_file: Path, settings_model: type[Settings]) -> None:
    """書いた値を読む（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.shared.settings import (
        LocalWhisperSettings,
        TranscriptionSettings,
        load_settings,
    )

    # 準備
    settings_file.write_text(
        '[transcription.local_whisper]\nmodel = "small"\n\n[[outputs]]\nid = "copy_only"\n',
        encoding="utf-8",
    )

    # 実行
    settings = load_settings(settings_file, settings_model)

    # 検証（書いていない項目は既定値）
    assert settings == settings_model(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small")),
        outputs=[CopyOnlySettings()],
    )


def _locate(dump: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
    """ドットで結んだ設定のキーの値を持つ表と、その表の中のキーを返す。

    `outputs.{出力先の ID}.{項目}` は outputs の id が一致する項目で引き、引けなければ KeyError にする。
    """
    parts = key.split(".")
    # 出力先のキーか
    if parts[0] == "outputs":
        # そう: id が一致する出力先の項目を引く
        output_id, leaf = parts[1], parts[2]
        for output in dump["outputs"]:
            if output["id"] == output_id:
                return output, leaf
        raise KeyError(key)
    # それ以外: 入れ子の表をたどる
    table = dump
    for part in parts[:-1]:
        table = table[part]
    return table, parts[-1]


def _dump_without(settings: Settings, keys: Iterable[str]) -> dict[str, Any]:
    """設定を dict にし、ドットで結んだキーの値を取り除いて返す。"""
    dump = settings.model_dump()
    for key in keys:
        table, leaf = _locate(dump, key)
        del table[leaf]
    return dump


def _values_in(dump: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """設定の dict から、ドットで結んだキーの値を引いて、キー → 値の dict にして返す。"""
    values: dict[str, Any] = {}
    for key in keys:
        table, leaf = _locate(dump, key)
        values[key] = table[leaf]
    return values


def _values_of(settings: Settings, keys: Iterable[str]) -> dict[str, Any]:
    """設定から、ドットで結んだキーの値を引いて、キー → 値の dict にして返す。"""
    return _values_in(settings.model_dump(), keys)


def test_load_settings_when_sample_file(repo_root: Path, settings_model: type[Settings]) -> None:
    """リポジトリの見本は共通の既定値（Windows の既定値）と一致する（正常系）。"""
    from voice_paste.shared.os_kind import CURRENT_OS
    from voice_paste.shared.settings import OS_DEFAULT_OVERRIDES, load_settings

    # 準備: この OS で既定値を上書きしているキー（上書きが無い OS は空）
    overridden_keys = list(OS_DEFAULT_OVERRIDES.get(CURRENT_OS, {}))

    # 実行
    settings = load_settings(repo_root / "settings.sample.toml", settings_model)

    # 検証: 上書きしているキー以外は既定値と等しく、上書きしているキーは見本が共通の既定値のまま
    assert _dump_without(settings, overridden_keys) == _dump_without(
        settings_model(), overridden_keys
    )
    assert _values_of(settings, overridden_keys) == {
        key: COMMON_DEFAULTS[key] for key in overridden_keys
    }


# === os_default ===


def test_os_default_when_linux() -> None:
    """Linux の上書きがあるキーは上書きの値になる（正常系）。"""
    from voice_paste.shared.os_kind import OsKind
    from voice_paste.shared.settings import os_default

    # 実行
    value = os_default("recording.lower_volume", True, os_kind=OsKind.LINUX)

    # 検証
    assert value is False


def test_os_default_when_windows() -> None:
    """Windows は共通の既定値になる（正常系）。"""
    from voice_paste.shared.os_kind import OsKind
    from voice_paste.shared.settings import os_default

    # 実行
    value = os_default("transcription.local_whisper.device", "cuda", os_kind=OsKind.WINDOWS)

    # 検証
    assert value == "cuda"


def test_os_default_when_not_overridden() -> None:
    """上書きの無いキーは共通の既定値になる（正常系）。"""
    from voice_paste.shared.os_kind import OsKind
    from voice_paste.shared.settings import os_default

    # 実行
    value = os_default("recording.hide_window", False, os_kind=OsKind.LINUX)

    # 検証
    assert value is False


def test_os_default_when_settings_model_linux() -> None:
    """Linux で組み立てた設定のモデルの既定値は、OS_DEFAULT_OVERRIDES[OsKind.LINUX] の全ての値になる（正常系）。"""
    # 実行: 子プロセスで CURRENT_OS を Linux にしてから main を import し、既定値と上書きを出させる
    completed = subprocess.run(
        [sys.executable, "-c", LINUX_SETTINGS_MODEL_SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    # 検証
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert set(result["overrides"]) == set(LINUX_DEFAULTS)
    assert _values_in(result["defaults"], LINUX_DEFAULTS) == LINUX_DEFAULTS


@pytest.mark.parametrize(
    ("content", "expected_key"),
    [
        pytest.param(
            '[transcription.local_whisper]\nbeam_size = "x"\n',
            r"transcription\.local_whisper\.beam_size",
            id="beam_size",
        ),
        pytest.param(
            '[transcription]\nengine = "gemini"\n',
            r"transcription\.engine",
            id="engine_unknown",
        ),
    ],
)
def test_load_settings_when_invalid_value(
    settings_file: Path, settings_model: type[Settings], content: str, expected_key: str
) -> None:
    """合わない値はキーを示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text(content, encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match=expected_key):
        load_settings(settings_file, settings_model)


@pytest.mark.parametrize(
    ("content", "expected_key"),
    [
        pytest.param(
            "[recording]\nvolum_percent = 30\n", r"recording\.volum_percent", id="typo"
        ),
        pytest.param(
            '[transcription.openai]\nmodle = "gpt-4o-mini-transcribe"\n',
            r"transcription\.openai\.modle",
            id="openai_typo",
        ),
    ],
)
def test_load_settings_when_unknown_key(
    settings_file: Path, settings_model: type[Settings], content: str, expected_key: str
) -> None:
    """知らないキーを断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text(content, encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match=expected_key):
        load_settings(settings_file, settings_model)


def test_load_settings_when_duplicate_output_id(
    settings_file: Path, settings_model: type[Settings]
) -> None:
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
        load_settings(settings_file, settings_model)


def test_load_settings_when_broken_toml(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """壊れた TOML を断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text("[recording\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError):
        load_settings(settings_file, settings_model)


def test_load_settings_when_ai_chat_remains(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """古い AI チャットの設定が残っていても読め、プリセットに読み替える（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset, load_settings

    # 準備
    content = (
        '[[outputs]]\nid = "paste_only"\n\n'
        '[[outputs]]\nid = "ai_chat"\nopen_delay_sec = 2.0\n\n'
        '[[outputs.targets]]\nname = "ChatGPT"\nurl = "https://chatgpt.com"\n'
        'hotkey = "<ctrl>+<alt>+1"\nenabled = true\n\n'
        '[[outputs.targets]]\nname = "Claude"\nurl = "https://claude.ai/new"\n'
        'hotkey = "<ctrl>+<alt>+3"\nenabled = false\n'
    )
    settings_file.write_text(content, encoding="utf-8")

    # 実行
    settings = load_settings(settings_file, settings_model)

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
    assert settings_file.read_text(encoding="utf-8") == content


def test_load_settings_when_invalid_preset(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """合わないプリセットはキーを示して断る（異常系）。"""
    from voice_paste.shared.errors import SettingsError
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text(
        '[[presets]]\nkind = "endpoint"\ntitle = "受信先"\nurl = "ftp://x"\n',
        encoding="utf-8",
    )

    # 実行・検証
    with pytest.raises(SettingsError, match=r"presets\[0\].*url"):
        load_settings(settings_file, settings_model)


# === save_settings ===


def test_save_settings_when_comments(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """コメントを保ったまま値を書き換える（正常系）。"""
    from voice_paste.shared.settings import (
        HotkeySettings,
        load_settings,
        save_settings,
    )

    # 準備
    settings_file.write_text(
        '# 録音まわりのホットキー\n[hotkeys]\n# 録音を始めるキー\nstart = "<ctrl>+<alt>+d"\n',
        encoding="utf-8",
    )
    new_settings = settings_model(hotkeys=HotkeySettings(start="<ctrl>+<alt>+s"))

    # 実行
    save_settings(settings_file, new_settings)

    # 検証
    text = settings_file.read_text(encoding="utf-8")
    assert "# 録音まわりのホットキー" in text
    assert "# 録音を始めるキー" in text
    assert load_settings(settings_file, settings_model).hotkeys.start == "<ctrl>+<alt>+s"


def test_save_settings_when_restart_item_changed(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """再起動が要る項目が変われば True（正常系）。"""
    from voice_paste.shared.settings import (
        LocalWhisperSettings,
        TranscriptionSettings,
        save_settings,
    )

    # 準備（large-v3 から small へ変える）
    settings_file.write_text(
        '[transcription.local_whisper]\nmodel = "large-v3"\n', encoding="utf-8"
    )
    new_settings = settings_model(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small"))
    )

    # 実行
    restart_required = save_settings(settings_file, new_settings)

    # 検証
    assert restart_required is True


def test_save_settings_when_immediate_item_changed(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """即時に効く項目だけなら False（正常系）。"""
    from voice_paste.shared.settings import HotkeySettings, save_settings

    # 準備
    settings_file.write_text(
        '[hotkeys]\nstart = "<ctrl>+<alt>+d"\n', encoding="utf-8"
    )
    new_settings = settings_model(hotkeys=HotkeySettings(start="<ctrl>+<alt>+s"))

    # 実行
    restart_required = save_settings(settings_file, new_settings)

    # 検証
    assert restart_required is False


def test_save_settings_when_missing(tmp_path: Path, settings_model: type[Settings]) -> None:
    """無ければフォルダごと作る（正常系）。"""
    from voice_paste.shared.settings import save_settings

    # 準備
    path = tmp_path / "not_created" / SETTINGS_FILE_NAME
    new_settings = settings_model()

    # 実行
    restart_required = save_settings(path, new_settings)

    # 検証
    written = tomllib.loads(path.read_text(encoding="utf-8"))
    assert restart_required is False
    assert path.exists()
    assert "glossary_path" not in written


def test_save_settings_when_invalid_existing(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """壊れたファイルは書き直して再起動が要るとする（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備
    settings_file.write_text("[recording\n", encoding="utf-8")

    # 実行
    restart_required = save_settings(settings_file, settings_model())

    # 検証
    assert restart_required is True
    assert load_settings(settings_file, settings_model) == settings_model()


def test_save_settings_when_glossary_reset(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """用語集の場所を既定（None）に戻すとキーを削除する（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備
    settings_file.write_text('glossary_path = "C:/x/yogo.csv"\n', encoding="utf-8")

    # 実行
    save_settings(settings_file, settings_model())

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert "glossary_path" not in written
    assert load_settings(settings_file, settings_model).glossary_path is None


def test_save_settings_when_ai_chat_remains(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """読み替えた設定を保存すると、ai_chat の項目が消えてプリセットとして書かれる（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備
    settings_file.write_text(
        '[[outputs]]\nid = "paste_only"\n\n'
        '[[outputs]]\nid = "ai_chat"\nopen_delay_sec = 2.0\n\n'
        '[[outputs.targets]]\nname = "ChatGPT"\nurl = "https://chatgpt.com"\n'
        'hotkey = "<ctrl>+<alt>+1"\nenabled = true\n\n'
        '[[outputs.targets]]\nname = "Claude"\nurl = "https://claude.ai/new"\n'
        'hotkey = "<ctrl>+<alt>+3"\nenabled = false\n',
        encoding="utf-8",
    )
    loaded = load_settings(settings_file, settings_model)

    # 実行
    restart_required = save_settings(settings_file, loaded)

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert restart_required is False
    assert [output["id"] for output in written["outputs"]] == ["paste_only"]
    assert [
        (preset["kind"], preset["title"], preset["url"], preset["hotkey"], preset["enabled"])
        for preset in written["presets"]
    ] == [
        ("browser", "ChatGPT", "https://chatgpt.com", "<ctrl>+<alt>+1", True),
        ("browser", "Claude", "https://claude.ai/new", "<ctrl>+<alt>+3", False),
    ]
    assert written["preset_options"]["browser"]["open_delay_sec"] == 2.0


def test_save_settings_when_glossaries(tmp_path: Path, settings_model: type[Settings]) -> None:
    """用語集の一覧を書き、設定のフォルダの下の場所は相対パスにする（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings, load_settings, save_settings

    # 準備（設定のフォルダの下の glossaries/glossary_1.csv と、別のフォルダの絶対パスの 2 件）
    settings_file = tmp_path / "conf" / SETTINGS_FILE_NAME
    other_path = tmp_path / "other" / "terms.csv"
    settings = settings_model(
        glossaries=[
            GlossarySettings(
                name="yogo", path=settings_file.parent / "glossaries" / "glossary_1.csv"
            ),
            GlossarySettings(name="会議用", path=other_path),
        ],
        active_glossary="会議用",
    )

    # 実行
    save_settings(settings_file, settings)

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert written["glossaries"][0]["path"] == "glossaries/glossary_1.csv"
    assert Path(written["glossaries"][1]["path"]) == other_path
    loaded = load_settings(settings_file, settings_model)
    assert [glossary.name for glossary in loaded.glossaries] == ["yogo", "会議用"]
    assert loaded.active_glossary == "会議用"


def test_save_settings_when_legacy_glossary_path(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """用語集の一覧を書くと、今までの glossary_path のキーを削除する（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings, save_settings

    # 準備（glossary_path を持つ settings.toml に、glossary_path が None で glossaries が 1 件の設定を書く）
    settings_file = tmp_path / "conf" / SETTINGS_FILE_NAME
    legacy_path = tmp_path / "elsewhere" / "yogo.csv"
    settings_file.parent.mkdir()
    settings_file.write_text(f'glossary_path = "{legacy_path.as_posix()}"\n', encoding="utf-8")
    settings = settings_model(glossaries=[GlossarySettings(name="yogo", path=legacy_path)])

    # 実行
    save_settings(settings_file, settings)

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert "glossary_path" not in written
    assert len(written["glossaries"]) == 1
    assert Path(written["glossaries"][0]["path"]) == legacy_path


def test_save_settings_when_glossary_presets(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """用語集のプリセットを書き、今までの active_glossary のキーを削除する（正常系）。"""
    from voice_paste.shared.settings import (
        GlossaryPresetSettings,
        GlossarySettings,
        load_settings,
        save_settings,
    )

    # 準備（active_glossary を持つ settings.toml に、active_glossary が None で 2 件の glossary_presets を持つ設定を書く）
    settings_file = tmp_path / "conf" / SETTINGS_FILE_NAME
    settings_file.parent.mkdir()
    settings_file.write_text('active_glossary = "会議用"\n', encoding="utf-8")
    settings = settings_model(
        glossaries=[
            GlossarySettings(name="yogo", path=settings_file.parent / "yogo.csv"),
            GlossarySettings(name="会議用", path=settings_file.parent / "meeting.csv"),
        ],
        active_glossary=None,
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
            GlossaryPresetSettings(name="議事録", glossaries=["会議用", "yogo"]),
        ],
        active_glossary_preset="議事録",
    )

    # 実行
    save_settings(settings_file, settings)

    # 検証
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    assert "active_glossary" not in written
    loaded = load_settings(settings_file, settings_model)
    assert loaded.glossary_presets == [
        GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
        GlossaryPresetSettings(name="議事録", glossaries=["会議用", "yogo"]),
    ]
    assert loaded.active_glossary_preset == "議事録"


@pytest.mark.parametrize(
    "hint_presets",
    [
        pytest.param(
            [
                {"name": "A", "words": ["a"], "enabled": True},
                {"name": "B", "words": ["b"], "enabled": True},
                {"name": "C", "words": ["c"], "enabled": True},
            ],
            id="added",
        ),
        pytest.param(
            [
                {"name": "A", "words": ["a", "aa"], "enabled": True},
                {"name": "B", "words": ["b"], "enabled": True},
            ],
            id="words_changed",
        ),
        pytest.param([{"name": "A", "words": ["a"], "enabled": True}], id="reduced"),
    ],
)
def test_save_settings_when_comment_after_array_table(
    settings_file: Path, settings_model: type[Settings], hint_presets: list[dict[str, Any]]
) -> None:
    """配列の表を入れ替えても、配列の表の後ろのコメントを残す（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備（2 件の `[[hint_presets]]` の後ろにコメント行と `[recording]` を続ける）
    settings_file.write_text(
        f"{HINT_PRESET_A}\n{HINT_PRESET_B}\n{COMMENT_AFTER_ARRAY_TABLE}\n"
        "[recording]\nfade_sec = 1.5\n",
        encoding="utf-8",
    )
    new_settings = settings_model.model_validate(
        {"hint_presets": hint_presets, "recording": {"fade_sec": 1.5}}
    )

    # 実行
    save_settings(settings_file, new_settings)

    # 検証
    text = settings_file.read_text(encoding="utf-8")
    assert text.count(COMMENT_AFTER_ARRAY_TABLE) == 1
    assert re.search(rf"{re.escape(COMMENT_AFTER_ARRAY_TABLE)}\n\[recording\]", text)
    assert load_settings(settings_file, settings_model).hint_presets == new_settings.hint_presets


@pytest.mark.parametrize(
    ("original", "new_values", "following"),
    [
        pytest.param(
            f"[api]\nport = 47824\n\n{HINT_PRESET_A}\n{COMMENT_AFTER_ARRAY_TABLE}\n"
            "[recording]\nfade_sec = 1.5\n",
            {"api": {"port": 47824}, "recording": {"fade_sec": 1.5}},
            r"\n\[recording\]",
            id="after_api_before_recording",
        ),
        pytest.param(
            f"{HINT_PRESET_A}\n{COMMENT_AFTER_ARRAY_TABLE}\n[recording]\nfade_sec = 1.5\n",
            {"recording": {"fade_sec": 1.5}},
            r"\n\[recording\]",
            id="first_table_before_recording",
        ),
        pytest.param(
            f"{HINT_PRESET_A}\n{COMMENT_AFTER_ARRAY_TABLE}\n"
            '[transcription.local_whisper]\nmodel = "small"\n',
            {"transcription": {"local_whisper": {"model": "small"}}},
            r"\n\[transcription\.local_whisper\]",
            id="before_super_table",
        ),
        pytest.param(
            f'{HINT_PRESET_A}\n{COMMENT_AFTER_ARRAY_TABLE}\n[[outputs]]\nid = "paste_only"\n',
            {"outputs": [{"id": "copy_only"}]},
            r"\n\[\[outputs\]\]",
            id="before_replaced_array_table",
        ),
        pytest.param(
            f"{HINT_PRESET_A}\n{COMMENT_AFTER_ARRAY_TABLE}\n",
            {},
            r"\n*\Z",
            id="no_table_after",
        ),
    ],
)
def test_save_settings_when_array_table_emptied(
    settings_file: Path,
    settings_model: type[Settings],
    original: str,
    new_values: dict[str, Any],
    following: str,
) -> None:
    """配列の表を 0 件にしても、配列の表の後ろのコメントを次の表の見出しの前に残す（正常系）。"""
    from voice_paste.shared.settings import load_settings, save_settings

    # 準備（1 件の `[[hint_presets]]` の後ろにコメント行を続け、hint_presets を 0 件にした設定を書く）
    settings_file.write_text(original, encoding="utf-8")
    new_settings = settings_model.model_validate({"hint_presets": [], **new_values})

    # 実行
    save_settings(settings_file, new_settings)

    # 検証
    text = settings_file.read_text(encoding="utf-8")
    loaded = load_settings(settings_file, settings_model)
    assert text.count(COMMENT_AFTER_ARRAY_TABLE) == 1
    assert re.search(re.escape(COMMENT_AFTER_ARRAY_TABLE) + following, text)
    assert loaded.hint_presets == []
    assert loaded == new_settings


# === find_hotkey_overlaps ===


def test_find_hotkey_overlaps() -> None:
    """前に並んだホットキーと重なるキーを、重なった組で返す（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.shared.settings import (
        BrowserPreset,
        Settings,
        find_hotkey_overlaps,
    )

    # 準備: 2 件目のプリセットの hotkey を、貼り付けのみと同じにする（確かめを飛ばして作る）
    settings = Settings.model_construct(
        outputs=[
            PasteAndSendSettings(hotkey="<ctrl>+<alt>+d"),
            PasteOnlySettings(hotkey="<ctrl>+<alt>+v"),
            CopyOnlySettings(hotkey="<ctrl>+<alt>+c"),
        ],
        presets=[
            BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1"),
            BrowserPreset(title="Claude", url="https://claude.ai/new", hotkey="<ctrl>+<alt>+v"),
        ],
    )

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == [("presets[1].hotkey", "outputs[1].hotkey")]


def test_find_hotkey_overlaps_when_presets_of_different_kinds() -> None:
    """種類をまたいだプリセットどうしの重なりを返す（正常系）。"""
    from voice_paste.shared.settings import (
        BrowserPreset,
        EndpointPreset,
        Settings,
        find_hotkey_overlaps,
    )

    # 準備
    settings = Settings.model_construct(
        presets=[
            BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+3"),
            EndpointPreset(title="受信先", url="http://127.0.0.1:9000/hook", hotkey="<ctrl>+<alt>+3"),
        ]
    )

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == [("presets[1].hotkey", "presets[0].hotkey")]


def test_find_hotkey_overlaps_when_start_equals_paste_and_send(
    settings_model: type[Settings],
) -> None:
    """録音の開始と貼り付けて送信が同じキー（既定）は重なりにしない（正常系）。"""
    from voice_paste.shared.settings import find_hotkey_overlaps

    # 実行
    overlaps = find_hotkey_overlaps(settings_model())

    # 検証
    assert overlaps == []


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            {
                "outputs": [
                    {"id": "paste_and_send"},
                    {"id": "paste_only"},
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
    settings_model: type[Settings], document: dict[str, object]
) -> None:
    """オフの出力先・無効のプリセットのホットキーは重なりにしない（正常系）。"""
    from voice_paste.shared.settings import find_hotkey_overlaps

    # 準備: ホットキーを一時停止と同じ <ctrl>+<alt>+z にしたものをオフ・無効にする
    settings = settings_model.model_validate(document)

    # 実行
    overlaps = find_hotkey_overlaps(settings)

    # 検証
    assert overlaps == []


def test_find_hotkey_overlaps_when_empty_preset_hotkeys() -> None:
    """空のホットキーのプリセットどうしは重なりにしない（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset, Settings, find_hotkey_overlaps

    # 準備
    settings = Settings(
        presets=[
            BrowserPreset(title="ChatGPT", url="https://chatgpt.com"),
            BrowserPreset(title="Claude", url="https://claude.ai/new"),
        ]
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
"""古い AI チャットの設定（送信先 2 件、開くまでの間 2.0 秒）を持つ settings.toml を素の dict にしたもの。"""


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


def test_settings_when_hotkeys_overlap() -> None:
    """ホットキーが重なる設定は、重なったキーと先のキーを持つ ValidationError で断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import Settings, list_validation_failures

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {"hotkeys": {"pause": "<ctrl>+<alt>+z", "cancel": "<ctrl>+<alt>+z"}}
        )
    failures = list_validation_failures(exc_info.value)
    assert len(failures) == 1
    key, reason = failures[0]
    assert key == "hotkeys.cancel"
    assert "hotkeys.pause" in reason


# === UiSettings の確かめ（_inherit_transcribing_show_hotkeys） ===


def test_ui_settings_when_transcribing_show_hotkeys_missing() -> None:
    """文字起こし中の表示の項目が無ければ録音の画面の値で読む（正常系）。"""
    from voice_paste.shared.settings import UiSettings

    # 実行
    ui = UiSettings.model_validate({"show_hotkeys": False})

    # 検証
    assert ui.show_hotkeys is False
    assert ui.transcribing_show_hotkeys is False


def test_ui_settings_when_both_show_hotkeys_missing() -> None:
    """どちらの項目も無ければ既定で読む（正常系）。"""
    from voice_paste.shared.settings import UiSettings

    # 実行
    ui = UiSettings.model_validate({})

    # 検証
    assert ui.show_hotkeys is True
    assert ui.transcribing_show_hotkeys is True


def test_ui_settings_when_transcribing_show_hotkeys_set() -> None:
    """文字起こし中の表示の項目があればその値で読む（正常系）。"""
    from voice_paste.shared.settings import UiSettings

    # 実行
    ui = UiSettings.model_validate({"show_hotkeys": False, "transcribing_show_hotkeys": True})

    # 検証
    assert ui.show_hotkeys is False
    assert ui.transcribing_show_hotkeys is True


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
            {
                "glossaries": [
                    {"name": "会議用", "path": "a.csv"},
                    {"name": "会議用", "path": "b.csv"},
                ]
            }
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["glossaries[1].name"]


def test_settings_when_glossary_name_blank(settings_model: type[Settings]) -> None:
    """空白だけの名前は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が「  」の glossaries）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate({"glossaries": [{"name": "  ", "path": "a.csv"}]})
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
            {
                "glossary_presets": [
                    {"name": "既定", "glossaries": []},
                    {"name": "既定", "glossaries": []},
                ]
            }
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
        settings_model.model_validate({"glossary_presets": [{"name": "  ", "glossaries": []}]})
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
            {"glossary_presets": [{"name": "既定", "glossaries": ["yogo", "yogo"]}]}
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
            {"edge_phrases": [{"text": "字幕*"}, {"text": " * ", "position": "start"}]}
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
    """settings.toml と同じ構造の表記のヒントのプリセット 1 件を返す。"""
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
    settings = settings_model.model_validate({"hint_presets": [_hint_preset("開発", [word])]})

    # 検証
    assert len(settings.hint_presets[0].words[0].encode("utf-8")) == HINT_LIMIT_BYTES


def test_settings_when_hint_too_long(settings_model: type[Settings]) -> None:
    """上限を 1 バイトでも超えたら通らない（異常系）。"""
    from pydantic import ValidationError

    # 準備（1 バイトの英字 + 日本語 74 文字 = 223 バイト）
    word = "a" + "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES)

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate({"hint_presets": [_hint_preset("開発", [word])]})
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
    settings = settings_model.model_validate({"hint_presets": presets})

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
        settings_model.model_validate({"hint_presets": presets})
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
        settings_model.model_validate({"hint_presets": [_hint_preset("開発", ["  "])]})
    assert [error["type"] for error in exc_info.value.errors()] == ["hint_word_empty"]
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["hint_presets[0].words[0]"]


def test_load_settings_when_no_hint_presets(
    settings_file: Path, settings_model: type[Settings]
) -> None:
    """hint_presets のキーが無い今の settings.toml を読める（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file.write_text('[transcription.local_whisper]\nmodel = "small"\n', encoding="utf-8")

    # 実行
    settings = load_settings(settings_file, settings_model)

    # 検証
    assert settings.hint_presets == []


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
            {"hint_presets": [_hint_preset("開発", ["A"]), _hint_preset("開発", ["B"])]}
        )
    failures = list_validation_failures(exc_info.value)
    assert [key for key, _reason in failures] == ["hint_presets[1].name"]


def test_settings_when_hint_preset_name_blank(settings_model: type[Settings]) -> None:
    """空白だけの名前は検証に通らない（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import list_validation_failures

    # 実行・検証（名前が「  」の hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate({"hint_presets": [_hint_preset("  ", ["A"])]})
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
    """渡したモデルで outputs を検証し、既定の一覧をその並びで持つ（正常系）。"""
    from voice_paste.shared.settings import build_settings_model

    # 準備
    model_a = _output_model("a")
    model_b = _output_model("b", delay_sec=1.0)
    model = build_settings_model([model_a, model_b])

    # 実行
    defaults = model()
    validated = model.model_validate(
        {"outputs": [{"id": "b", "hotkey": "<ctrl>+<alt>+b", "delay_sec": 2.0}]}
    )

    # 検証
    assert [type(output) for output in defaults.outputs] == [model_a, model_b]
    assert type(validated.outputs[0]) is model_b
    assert validated.outputs[0].delay_sec == 2.0
    assert validated.model_dump(mode="json")["outputs"][0]["delay_sec"] == 2.0
    assert model.output_models == {"a": model_a, "b": model_b}


def test_build_settings_model_when_unknown_output() -> None:
    """渡していない出力先の ID を断る（異常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import build_settings_model, list_validation_failures

    # 準備
    model = build_settings_model([_output_model("a"), _output_model("b")])

    # 実行・検証
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({"outputs": [{"id": "c"}]})
    keys = [key for key, _reason in list_validation_failures(exc_info.value)]
    assert keys != []
    assert all(key.startswith("outputs[0]") for key in keys)


def test_build_settings_model_when_single_output() -> None:
    """出力先が 1 つでも組み立てられる（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.shared.settings import build_settings_model, list_validation_failures

    # 準備
    model_a = _output_model("a")
    model = build_settings_model([model_a])

    # 実行・検証
    assert [type(output) for output in model().outputs] == [model_a]
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({"outputs": [{"id": "a", "hotkey": 1}]})
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
