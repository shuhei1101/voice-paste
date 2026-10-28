"""動いている OS の判定。OS ごとの実装・既定値を選ぶ唯一の場所。"""

from __future__ import annotations

import sys
from enum import StrEnum


class OsKind(StrEnum):
    """動いている OS。main.py の配線が OS ごとの実装を、設定のモデルが OS ごとの既定値を選ぶのに使う。"""

    WINDOWS = "windows"
    LINUX = "linux"


def detect_os(platform: str = sys.platform) -> OsKind:
    """sys.platform の値から OsKind を返す。"""
    # win32 か
    if platform == "win32":
        # そう: Windows
        return OsKind.WINDOWS
    # それ以外: Linux（対応するのは Ubuntu 24.04 の Xorg のセッション）
    return OsKind.LINUX


CURRENT_OS: OsKind = detect_os()
"""読み込んだときに detect_os で決めた、動いている OS。OS を見る処理は sys.platform を直に読まず、これを読むか main.py の配線で渡される。"""
