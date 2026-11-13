"""runtime/settings_store.py（SettingsStore の replace）の単体テスト。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.unit.voice_paste.settings_helpers import MakeSettings
    from voice_paste.shared.settings import Settings

NEW_VOLUME_PERCENT = 30


def test_replace(default_settings: Settings, make_settings: MakeSettings) -> None:
    """入れ替えた設定を読める（正常系）。"""
    from voice_paste.runtime.settings_store import SettingsStore

    # 準備
    store = SettingsStore(default_settings)
    new_settings = make_settings({"recording": {"volume_percent": NEW_VOLUME_PERCENT}})

    # 実行
    store.replace(new_settings)

    # 検証
    assert store.get().recording.volume_percent == NEW_VOLUME_PERCENT


def test_get_when_pinned(default_settings: Settings, make_settings: MakeSettings) -> None:
    """固定している間は入れ替えた設定を返さない（正常系）。"""
    from voice_paste.runtime.settings_store import SettingsStore

    # 準備
    store = SettingsStore(default_settings)
    new_settings = make_settings({"recording": {"volume_percent": NEW_VOLUME_PERCENT}})

    # 実行: 固定してから入れ替え、固定を解く
    store.pin()
    store.replace(new_settings)
    pinned = store.get()
    latest = store.latest()
    store.unpin()
    unpinned = store.get()

    # 検証
    assert pinned is default_settings
    assert latest.recording.volume_percent == NEW_VOLUME_PERCENT
    assert unpinned.recording.volume_percent == NEW_VOLUME_PERCENT
