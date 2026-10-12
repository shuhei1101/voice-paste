"""shared/settings.py（load_settings・save_settings・find_hotkey_overlaps・find_glossary_name_overlaps・migrate_ai_chat・build_settings_model・Settings の確かめ）の単体テスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest

if TYPE_CHECKING:
    from voice_paste.shared.settings import OutputSettingsBase, Settings

SETTINGS_FILE_NAME = "settings.toml"


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


def test_load_settings_when_sample_file(repo_root: Path, settings_model: type[Settings]) -> None:
    """リポジトリの見本は既定値と一致する（正常系）。"""
    from voice_paste.shared.settings import load_settings

    # 実行
    settings = load_settings(repo_root / "settings.sample.toml", settings_model)

    # 検証
    assert settings == settings_model()


@pytest.mark.parametrize(
    ("content", "expected_key"),
    [
        pytest.param(
            '[transcription.local_whisper]\nbeam_size = "x"\n',
            r"transcription\.local_whisper\.beam_size",
            id="beam_size",
        ),
        pytest.param(
            '[transcription]\nengine = "openai"\n',
            r"transcription\.engine",
            id="engine_openai",
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
            '[transcription.openai]\nmodel = "whisper-1"\n',
            r"transcription\.openai",
            id="removed_openai_table",
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
        '[[presets]]\nkind = "endpoint"\ntitle = "受け口"\nurl = "ftp://x"\n',
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
    """用語集の場所を既定（None）に戻すとキーを消す（正常系）。"""
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
    """用語集の一覧を書くと、今までの glossary_path のキーを消す（正常系）。"""
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
        outputs=[PasteAndSendSettings(), PasteOnlySettings(), CopyOnlySettings()],
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
            EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook", hotkey="<ctrl>+<alt>+3"),
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
"""古い AI チャットの設定（送り先 2 件、開くまでの間 2.0 秒）を持つ settings.toml を素の dict にしたもの。"""


def test_migrate_ai_chat() -> None:
    """送り先をブラウザ添付のプリセットにし、ai_chat を外す（正常系）。"""
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
    """オフの AI チャットの送り先は無効のプリセットにする（正常系）。"""
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
        Settings.model_validate({"hotkeys": {"cancel": "<ctrl>+<alt>+z"}})
    failures = list_validation_failures(exc_info.value)
    assert len(failures) == 1
    key, reason = failures[0]
    assert key == "hotkeys.cancel"
    assert "hotkeys.pause" in reason


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
