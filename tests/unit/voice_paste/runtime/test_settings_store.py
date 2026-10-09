"""runtime/settings_store.py（SettingsStore の replace）の単体テスト。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voice_paste.shared.settings import Settings

NEW_VOLUME_PERCENT = 30


def test_replace(settings_model: type[Settings]) -> None:
    """入れ替えた設定を読める（正常系）。"""
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import RecordingSettings

    # 準備
    store = SettingsStore(settings_model())
    new_settings = settings_model(recording=RecordingSettings(volume_percent=NEW_VOLUME_PERCENT))

    # 実行
    store.replace(new_settings)

    # 検証
    assert store.get().recording.volume_percent == NEW_VOLUME_PERCENT
