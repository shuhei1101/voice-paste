"""既定値 → 環境の値 → checkout の上書きの順に重ねて読む結合テスト（シナリオ『常駐アプリを起動する』の「checkout の上書きがある」）。

実際のファイルを読み書きする。checkout の上書きの場所は一時フォルダへ差し替え、手元の settings.local.yaml に触れない。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.support.settings import load_test_default_settings
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.settings import load_settings, save_settings

HOTKEY_A = "<ctrl>+<alt>+<shift>+a"
"""環境の値で替える録音開始のホットキー（組み合わせ A）。"""

HOTKEY_B = "<ctrl>+<alt>+<shift>+b"
"""checkout の上書きで替える録音開始のホットキー（組み合わせ B）。"""

ENV_SETTINGS = f"""\
hotkeys:
  start: {HOTKEY_A}
recording:
  fade_sec: 1.25
edge_phrases:
  - text: 環境の値の文言
    position: start
"""
"""環境の値（settings.yaml）。録音開始のホットキー・音量を戻す秒数・文頭と文末から削除する文言を替える。"""

LOCAL_SETTINGS = f"""\
hotkeys:
  start: {HOTKEY_B}
recording:
  volume_percent: 70
"""
"""checkout の上書き（settings.local.yaml）。録音開始のホットキーと録音中の音量の割合を替える。"""


def _paths_with_local(tmp_path: Path) -> AppPaths:
    """設定の置き場所を tmp_path の下にし、checkout の上書きを一時フォルダの settings.local.yaml にした AppPaths を返す。"""
    paths = dataclasses.replace(
        resolve_app_paths(tmp_path / "data"),
        local_settings_file=tmp_path / "checkout" / "settings.local.yaml",
    )
    paths.settings_file.parent.mkdir(parents=True)
    assert paths.local_settings_file is not None
    paths.local_settings_file.parent.mkdir(parents=True)
    return paths


def test_normal_when_local_settings(tmp_path: Path) -> None:
    """既定値 → 環境の値 → checkout の上書きの順に重ね、後のレイヤーが勝つ。表はキーごと、一覧は丸ごと重なり、どのファイルも書き換えない（正常系）。"""
    # 準備
    paths = _paths_with_local(tmp_path)
    assert paths.local_settings_file is not None
    paths.settings_file.write_text(ENV_SETTINGS, encoding="utf-8")
    paths.local_settings_file.write_text(LOCAL_SETTINGS, encoding="utf-8")
    defaults = load_test_default_settings()

    # 実行
    settings = load_settings(paths, SETTINGS_MODEL)

    # 検証
    assert settings.hotkeys.start == HOTKEY_B
    assert settings.hotkeys.pause == defaults.hotkeys.pause
    assert settings.recording.fade_sec == 1.25
    assert settings.recording.volume_percent == 70
    assert settings.recording.lower_volume == defaults.recording.lower_volume
    assert [(phrase.text, phrase.position) for phrase in settings.edge_phrases] == [
        ("環境の値の文言", "start")
    ]
    assert paths.settings_file.read_text(encoding="utf-8") == ENV_SETTINGS
    assert paths.local_settings_file.read_text(encoding="utf-8") == LOCAL_SETTINGS


def test_normal_when_saved_with_local_settings(tmp_path: Path) -> None:
    """checkout の上書きがあるときの保存は、変えたキーだけを settings.yaml へ書き、settings.local.yaml を書き換えない（正常系）。"""
    # 準備
    paths = _paths_with_local(tmp_path)
    assert paths.local_settings_file is not None
    paths.local_settings_file.write_text(LOCAL_SETTINGS, encoding="utf-8")
    previous = load_settings(paths, SETTINGS_MODEL)
    changed = previous.model_copy(
        update={"recording": previous.recording.model_copy(update={"fade_sec": 1.25})}
    )

    # 実行
    save_settings(paths, previous, changed)

    # 検証
    assert paths.settings_file.read_text(encoding="utf-8") == "recording:\n  fade_sec: 1.25\n"
    assert paths.local_settings_file.read_text(encoding="utf-8") == LOCAL_SETTINGS
    reloaded = load_settings(paths, SETTINGS_MODEL)
    assert reloaded.recording.fade_sec == 1.25
    assert reloaded.hotkeys.start == HOTKEY_B
