"""動いている OS とデスクトップのセッションの判定と、OS ごとに使えない機能。OS ごとの実装・既定値・機能を選ぶ唯一の場所。"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from enum import StrEnum


class OsKind(StrEnum):
    """動いている OS。main.py の配線が OS ごとの実装を、設定のモデルが OS ごとの既定値を選ぶのに使う。"""

    WINDOWS = "windows"
    LINUX = "linux"


class DisplaySession(StrEnum):
    """Linux のデスクトップのセッションの種類。main.py の配線が、Linux のホットキー・貼り付けのキー・画面の実装を選ぶのに使う（Windows では使わない）。"""

    X11 = "x11"
    """Xorg のセッション（`XDG_SESSION_TYPE` が `wayland` 以外。無いときを含む）。"""

    WAYLAND = "wayland"
    """Wayland のセッション（`XDG_SESSION_TYPE` が `wayland`）。"""


class Feature(StrEnum):
    """OS で使えるかが分かれる機能。OS_UNAVAILABLE_FEATURES と FEATURE_SETTING_KEYS のキー。"""

    LOWER_VOLUME = "lower_volume"
    """録音中にシステムの音量を下げ、終わったら戻す。"""

    WEB_TRANSCRIPTION = "web_transcription"
    """`/web/` の下の画面と API・ブラウザの音声のジョブのキュー。"""

    HAAS_ENGINE = "haas_engine"
    """WSL の中の Haas の文字起こしのサーバーで起こす。"""


def detect_os(platform: str = sys.platform) -> OsKind:
    """sys.platform の値から OsKind を返す。"""
    # win32 か
    if platform == "win32":
        # そう: Windows
        return OsKind.WINDOWS
    # それ以外: Linux（対応するのは Ubuntu 24.04 の Xorg のセッションと、GNOME の Wayland のセッション）
    return OsKind.LINUX


def detect_display_session(environ: Mapping[str, str]) -> DisplaySession:
    """環境変数 `XDG_SESSION_TYPE` から DisplaySession を返す。"""
    # wayland か
    if environ.get("XDG_SESSION_TYPE") == "wayland":
        # そう: Wayland のセッション
        return DisplaySession.WAYLAND
    # それ以外（無いときを含む）: Xorg のセッション
    return DisplaySession.X11


CURRENT_OS: OsKind = detect_os()
"""読み込んだときに detect_os で決めた、動いている OS。OS を見る処理は sys.platform を直に読まず、これを読むか main.py の配線で渡される。"""

OS_UNAVAILABLE_FEATURES: Mapping[OsKind, frozenset[Feature]] = {
    OsKind.LINUX: frozenset({Feature.LOWER_VOLUME, Feature.WEB_TRANSCRIPTION, Feature.HAAS_ENGINE}),
}
"""その OS では使えない機能。載っていない OS は全ての機能を使える。OS で機能を止めるのはこの表だけで決める。"""

FEATURE_SETTING_KEYS: Mapping[Feature, frozenset[str]] = {
    Feature.LOWER_VOLUME: frozenset(
        {"recording.lower_volume", "recording.volume_percent", "recording.fade_sec"}
    ),
    Feature.WEB_TRANSCRIPTION: frozenset({"api.allowed_web_origins"}),
    Feature.HAAS_ENGINE: frozenset(
        {
            "transcription.haas.distribution",
            "transcription.haas.port",
            "transcription.haas.model",
            "transcription.haas.dtype",
            "transcription.haas.device",
            "transcription.haas.alpha",
            "transcription.haas.guard",
            "transcription.haas.short_audio_limit_sec",
            "transcription.haas.chunk_sec",
            "transcription.haas.search_sec",
            "transcription.haas.window_sec",
            "transcription.haas.separator",
            "transcription.haas.batch_size",
        }
    ),
}
"""機能だけが使う設定のキー（設定のドットで結んだキー）。その機能を使えない OS では、設定画面にこれらの欄を出さない。"""


def unavailable_features(os_kind: OsKind) -> frozenset[Feature]:
    """その OS で使えない機能を OS_UNAVAILABLE_FEATURES から返す（無ければ空）。"""
    return OS_UNAVAILABLE_FEATURES.get(os_kind, frozenset())


def hidden_setting_keys(features: Iterable[Feature]) -> frozenset[str]:
    """使えない機能の設定のキーを FEATURE_SETTING_KEYS から集めて返す（設定画面で出さない欄）。"""
    return frozenset().union(*(FEATURE_SETTING_KEYS.get(feature, frozenset()) for feature in features))
