"""integrations/keyboard/active_window_linux.py（read_active_wm_class）の単体テスト。

Xlib.display.Display は Mock に差し替え、実機の X サーバーにはつながない。
Linux の実装（python-xlib）を読み込むため、Windows では流さない。
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Linux 専用の実装を読み込むため Windows では流さない"
)

ACTIVE_WINDOW_ID = 0x1234
"""既定で `_NET_ACTIVE_WINDOW` が指すウィンドウの ID。"""

TERMINAL_WM_CLASS = ("gnome-terminal-server", "Gnome-terminal")
"""既定でアクティブなウィンドウの WM_CLASS（インスタンス名, クラス名）。"""


@pytest.fixture
def display_class(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Xlib.display.Display を差し替えた Mock を返す。

    `display_class.return_value` が、つないだ Display。既定は `_NET_ACTIVE_WINDOW` が 0x1234 を指し、
    そのウィンドウの WM_CLASS が ("gnome-terminal-server", "Gnome-terminal")。
    実装が Display を `Xlib.display.Display` で引いても、名前で import しても差し替わる。
    """
    import Xlib.display

    from voice_paste.integrations.keyboard import active_window_linux

    display = MagicMock()
    display.screen.return_value.root.get_full_property.return_value = MagicMock(
        value=[ACTIVE_WINDOW_ID]
    )
    display.create_resource_object.return_value.get_wm_class.return_value = TERMINAL_WM_CLASS
    mock = MagicMock(return_value=display)
    monkeypatch.setattr(Xlib.display, "Display", mock)
    monkeypatch.setattr(active_window_linux, "Display", mock, raising=False)
    return mock


def _warning_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """caplog に残った WARNING のログを返す。"""
    return [record for record in caplog.records if record.levelno == logging.WARNING]


def test_read_active_wm_class(display_class: MagicMock) -> None:
    """アクティブなウィンドウの WM_CLASS を返す（正常系）。"""
    from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class

    # 実行
    result = read_active_wm_class()

    # 検証
    display = display_class.return_value
    assert result == ("gnome-terminal-server", "Gnome-terminal")
    display.create_resource_object.assert_called_once_with("window", 0x1234)
    display.close.assert_called_once()


def test_read_active_wm_class_when_no_active_window(display_class: MagicMock) -> None:
    """アクティブなウィンドウが無ければ空を返す（正常系）。"""
    from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class

    # 準備
    display = display_class.return_value
    display.screen.return_value.root.get_full_property.return_value = None

    # 実行
    result = read_active_wm_class()

    # 検証
    assert result == ()
    display.close.assert_called_once()


def test_read_active_wm_class_when_no_wm_class(display_class: MagicMock) -> None:
    """WM_CLASS が無ければ空を返す（正常系）。"""
    from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class

    # 準備
    display = display_class.return_value
    display.create_resource_object.return_value.get_wm_class.return_value = None

    # 実行
    result = read_active_wm_class()

    # 検証
    assert result == ()


def test_read_active_wm_class_when_display_error(
    display_class: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """X サーバーへつなげなければ空を返し、WARNING を出す（異常系）。"""
    import Xlib.error

    from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class

    # 準備
    display_class.side_effect = Xlib.error.DisplayNameError(":99")
    caplog.set_level(logging.WARNING)

    # 実行
    result = read_active_wm_class()

    # 検証
    assert result == ()
    assert len(_warning_logs(caplog)) == 1


def test_read_active_wm_class_when_x_error(display_class: MagicMock) -> None:
    """ウィンドウが読めなければ空を返して Display を閉じる（異常系）。"""
    import Xlib.error

    from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class

    # 準備（BadWindow は X サーバーの応答の 32 バイトから組み立てる）
    display = display_class.return_value
    display.create_resource_object.return_value.get_wm_class.side_effect = Xlib.error.BadWindow(
        MagicMock(), bytes(32)
    )

    # 実行
    result = read_active_wm_class()

    # 検証
    assert result == ()
    display.close.assert_called_once()
