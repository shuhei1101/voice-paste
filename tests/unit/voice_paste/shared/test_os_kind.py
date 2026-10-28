"""shared/os_kind.py（detect_os）の単体テスト。"""

from __future__ import annotations


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
