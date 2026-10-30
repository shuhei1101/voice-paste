"""shared/os_kind.py（detect_os・detect_display_session・unavailable_features・hidden_setting_keys）の単体テスト。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from voice_paste.shared.settings import Settings


def _untraceable_keys(settings: Settings, keys: Iterable[str]) -> list[str]:
    """ドットで結んだ設定のキーのうち、設定のモデルの値から辿れないものを返す。"""
    untraceable: list[str] = []
    for key in keys:
        node: object = settings
        for part in key.split("."):
            if not hasattr(node, part):
                untraceable.append(key)
                break
            node = getattr(node, part)
    return untraceable


def test_detect_os_when_windows() -> None:
    """win32 は Windows と判定する（正常系）。"""
    from voice_paste.shared.os_kind import OsKind, detect_os

    # 実行
    os_kind = detect_os("win32")

    # 検証
    assert os_kind is OsKind.WINDOWS


def test_detect_os_when_linux() -> None:
    """linux は Linux と判定する（正常系）。"""
    from voice_paste.shared.os_kind import OsKind, detect_os

    # 実行
    os_kind = detect_os("linux")

    # 検証
    assert os_kind is OsKind.LINUX


# === detect_display_session ===


def test_detect_display_session_when_wayland() -> None:
    """wayland は Wayland のセッションと判定する（正常系）。"""
    from voice_paste.shared.os_kind import DisplaySession, detect_display_session

    # 実行
    session = detect_display_session({"XDG_SESSION_TYPE": "wayland"})

    # 検証
    assert session is DisplaySession.WAYLAND


def test_detect_display_session_when_x11() -> None:
    """x11 は Xorg のセッションと判定する（正常系）。"""
    from voice_paste.shared.os_kind import DisplaySession, detect_display_session

    # 実行
    session = detect_display_session({"XDG_SESSION_TYPE": "x11"})

    # 検証
    assert session is DisplaySession.X11


def test_detect_display_session_when_missing() -> None:
    """環境変数が無ければ Xorg のセッションと判定する（正常系）。"""
    from voice_paste.shared.os_kind import DisplaySession, detect_display_session

    # 実行
    session = detect_display_session({})

    # 検証
    assert session is DisplaySession.X11


# === unavailable_features ===


def test_unavailable_features_when_linux() -> None:
    """Linux は音量と外の端末のブラウザの機能を使えない（正常系）。"""
    from voice_paste.shared.os_kind import Feature, OsKind, unavailable_features

    # 実行
    features = unavailable_features(OsKind.LINUX)

    # 検証
    assert features == frozenset({Feature.LOWER_VOLUME, Feature.WEB_TRANSCRIPTION})


def test_unavailable_features_when_windows() -> None:
    """Windows は全ての機能を使える（正常系）。"""
    from voice_paste.shared.os_kind import OsKind, unavailable_features

    # 実行
    features = unavailable_features(OsKind.WINDOWS)

    # 検証
    assert features == frozenset()


# === hidden_setting_keys ===


def test_hidden_setting_keys() -> None:
    """使えない機能の設定のキーを集める（正常系）。"""
    from voice_paste.shared.os_kind import OsKind, hidden_setting_keys, unavailable_features

    # 実行
    keys = hidden_setting_keys(unavailable_features(OsKind.LINUX))

    # 検証
    assert keys == frozenset(
        {
            "recording.lower_volume",
            "recording.volume_percent",
            "recording.fade_sec",
            "api.allowed_web_origins",
        }
    )


def test_hidden_setting_keys_when_empty() -> None:
    """使えない機能が無ければ空になる（正常系）。"""
    from voice_paste.shared.os_kind import hidden_setting_keys

    # 実行
    keys = hidden_setting_keys(frozenset())

    # 検証
    assert keys == frozenset()


def test_hidden_setting_keys_when_keys_exist() -> None:
    """表の設定のキーは全て設定のモデルにある（正常系）。"""
    from voice_paste.shared.os_kind import FEATURE_SETTING_KEYS, hidden_setting_keys
    from voice_paste.shared.settings import Settings

    # 準備
    all_keys = hidden_setting_keys(FEATURE_SETTING_KEYS.keys())

    # 実行
    untraceable = _untraceable_keys(Settings(), all_keys)

    # 検証
    assert untraceable == []
