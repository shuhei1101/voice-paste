"""古い AI チャットの設定が残った settings.toml の読み替えと保存の結合テスト。

実際のファイルを読み書きし、プリセットに読み替えて起動できること、保存すると ai_chat の項目が無くなり同じ送り先がプリセットとして書かれることを確かめる。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import load_settings, save_settings

AI_CHAT_SETTINGS = """\
[[outputs]]
id = "paste_and_send"

[[outputs]]
id = "paste_only"

[[outputs]]
id = "copy_only"

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
"""前の版の既定の一覧で作られた settings.toml（ai_chat の項目に送り先 3 件）。"""

EXPECTED_PRESETS = [
    ("browser", "ChatGPT", "https://chatgpt.com", "<ctrl>+<alt>+1", True),
    ("browser", "Google AI", "https://gemini.google.com/app", "<ctrl>+<alt>+2", True),
    ("browser", "Claude", "https://claude.ai/new", "<ctrl>+<alt>+3", False),
]
"""読み替えたプリセットの（種類・タイトル・URL・ホットキー・有効）。"""


def test_normal_when_ai_chat_remains(tmp_path: Path) -> None:
    """ai_chat の項目が残った settings.toml を読むとプリセットに読み替え、保存すると ai_chat の項目が無くなる（正常系）。"""
    # 準備
    path = tmp_path / "settings.toml"
    path.write_text(AI_CHAT_SETTINGS, encoding="utf-8")

    # 実行（読んで、そのまま保存する）
    settings = load_settings(path, SETTINGS_MODEL)
    loaded_presets = [
        (preset.kind, preset.title, preset.url, preset.hotkey, preset.enabled)
        for preset in settings.presets
    ]
    save_settings(path, settings)

    # 検証
    assert loaded_presets == EXPECTED_PRESETS
    assert settings.preset_options.browser.open_delay_sec == 2.0
    written = tomllib.loads(path.read_text(encoding="utf-8"))
    assert [output["id"] for output in written["outputs"]] == [
        "paste_and_send",
        "paste_only",
        "copy_only",
    ]
    assert [
        (p["kind"], p["title"], p["url"], p["hotkey"], p["enabled"]) for p in written["presets"]
    ] == EXPECTED_PRESETS
    assert all(preset["send_enter"] is True for preset in written["presets"])
    assert written["preset_options"]["browser"]["open_delay_sec"] == 2.0
    assert 'id = "ai_chat"' not in path.read_text(encoding="utf-8")
    # 書き直した設定を読み直しても、同じプリセットになる
    assert [p.title for p in load_settings(path, SETTINGS_MODEL).presets] == ["ChatGPT", "Google AI", "Claude"]
