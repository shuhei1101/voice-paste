"""前のバージョンの settings.toml と、古い AI チャットの設定が残った settings.yaml の読み替えと保存の結合テスト。

実際のファイルを読み書きし、settings.toml を settings.yaml へ移してプリセットに読み替えて起動できること、
保存すると ai_chat の項目が無くなり同じ送信先がプリセットとして書かれることを確かめる。
"""

from __future__ import annotations

from pathlib import Path

from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.constants import resolve_app_paths
from voice_paste.shared.settings import load_settings, save_settings
from voice_paste.shared.yaml_document import read_yaml_mapping

AI_CHAT_TOML = """\
[[outputs]]
id = "paste_and_send"
hotkey = "<ctrl>+<alt>+d"

[[outputs]]
id = "paste_only"
hotkey = "<ctrl>+<alt>+v"

[[outputs]]
id = "copy_only"
hotkey = "<ctrl>+<alt>+c"

[[outputs]]
id = "ai_chat"
open_delay_sec = 2.0

[[outputs.targets]]
name = "ChatGPT"
url = "https://chatgpt.com"
hotkey = "<ctrl>+<alt>+1"
enabled = true

[[outputs.targets]]
name = "Google AI"
url = "https://gemini.google.com/app"
hotkey = "<ctrl>+<alt>+2"
enabled = true

[[outputs.targets]]
name = "Claude"
url = "https://claude.ai/new"
hotkey = "<ctrl>+<alt>+3"
enabled = false
"""
"""前のバージョンの既定の一覧で作られた settings.toml（ai_chat の項目に送信先 3 件）。"""

AI_CHAT_YAML = """\
outputs:
  - id: paste_and_send
    hotkey: <ctrl>+<alt>+d
  - id: paste_only
    hotkey: <ctrl>+<alt>+v
  - id: copy_only
    hotkey: <ctrl>+<alt>+c
  - id: ai_chat
    open_delay_sec: 2.0
    targets:
      - name: ChatGPT
        url: https://chatgpt.com
        hotkey: <ctrl>+<alt>+1
        enabled: true
      - name: Google AI
        url: https://gemini.google.com/app
        hotkey: <ctrl>+<alt>+2
        enabled: true
      - name: Claude
        url: https://claude.ai/new
        hotkey: <ctrl>+<alt>+3
        enabled: false
"""
"""古い AI チャットの設定が残った settings.yaml（settings.toml と同じ中身）。"""

EXPECTED_PRESETS = [
    ("browser", "ChatGPT", "https://chatgpt.com", "<ctrl>+<alt>+1", True),
    ("browser", "Google AI", "https://gemini.google.com/app", "<ctrl>+<alt>+2", True),
    ("browser", "Claude", "https://claude.ai/new", "<ctrl>+<alt>+3", False),
]
"""読み替えたプリセットの（種類・タイトル・URL・ホットキー・有効）。"""

EXPECTED_OUTPUT_IDS = ["paste_and_send", "paste_only", "copy_only"]
"""読み替えた後の出力先の ID の並び（ai_chat が無い）。"""


def test_normal_when_only_settings_toml(tmp_path: Path) -> None:
    """settings.yaml が無く ai_chat の項目が残った settings.toml だけがあると、settings.yaml へプリセットとして移し、settings.toml は残す（正常系）。"""
    # 準備
    paths = resolve_app_paths(tmp_path)
    paths.legacy_settings_file.write_text(AI_CHAT_TOML, encoding="utf-8")

    # 実行
    settings = load_settings(paths, SETTINGS_MODEL)

    # 検証
    assert [
        (preset.kind, preset.title, preset.url, preset.hotkey, preset.enabled)
        for preset in settings.presets
    ] == EXPECTED_PRESETS
    assert settings.preset_options.browser.open_delay_sec == 2.0
    written = read_yaml_mapping(paths.settings_file)
    assert [output["id"] for output in written["outputs"]] == EXPECTED_OUTPUT_IDS
    assert [
        (p["kind"], p["title"], p["url"], p["hotkey"], p["enabled"]) for p in written["presets"]
    ] == EXPECTED_PRESETS
    assert written["preset_options"] == {"browser": {"open_delay_sec": 2.0}}
    assert paths.legacy_settings_file.read_text(encoding="utf-8") == AI_CHAT_TOML
    # 移した settings.yaml を読み直しても、同じプリセットになる
    assert [p.title for p in load_settings(paths, SETTINGS_MODEL).presets] == [
        "ChatGPT",
        "Google AI",
        "Claude",
    ]


def test_normal_when_ai_chat_remains(tmp_path: Path) -> None:
    """ai_chat の項目が残った settings.yaml を読むとプリセットに読み替え、保存すると ai_chat の項目が無くなる（正常系）。"""
    # 準備
    paths = resolve_app_paths(tmp_path)
    paths.settings_file.write_text(AI_CHAT_YAML, encoding="utf-8")

    # 実行（読んで、読み替える前と同じ設定から保存する）
    settings = load_settings(paths, SETTINGS_MODEL)
    loaded_text = paths.settings_file.read_text(encoding="utf-8")
    save_settings(paths, settings, settings)

    # 検証
    assert [
        (preset.kind, preset.title, preset.url, preset.hotkey, preset.enabled)
        for preset in settings.presets
    ] == EXPECTED_PRESETS
    assert settings.preset_options.browser.open_delay_sec == 2.0
    assert loaded_text == AI_CHAT_YAML
    written = read_yaml_mapping(paths.settings_file)
    assert [
        (p["kind"], p["title"], p["url"], p["hotkey"], p["enabled"]) for p in written["presets"]
    ] == EXPECTED_PRESETS
    assert all(preset["send_enter"] is True for preset in written["presets"])
    assert written["preset_options"]["browser"]["open_delay_sec"] == 2.0
    assert "ai_chat" not in paths.settings_file.read_text(encoding="utf-8")
    # 書き直した設定を読み直しても、ai_chat の無い出力先と同じプリセットになる
    reloaded = load_settings(paths, SETTINGS_MODEL)
    assert [output.id for output in reloaded.outputs] == EXPECTED_OUTPUT_IDS
    assert [p.title for p in reloaded.presets] == ["ChatGPT", "Google AI", "Claude"]
