"""integrations/keyboard/sender_linux.py（send_paste_linux）の単体テスト。

pynput.keyboard.Controller・time.sleep・read_active_wm_class は Mock に差し替え、実機のキー入力と X サーバーには触れない。
Linux の実装を読み込むため、Windows では流さない。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call

import pytest
from pynput import keyboard

from voice_paste.shared.errors import DeliveryError

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Linux 専用の実装を読み込むため Windows では流さない"
)

V_KEY = keyboard.KeyCode.from_vk(0x76)
"""主キー `v` を XTEST で送信するキー（Xorg の pynput では vk が keysym で、ASCII の文字は文字コードと同じ）。"""


@pytest.fixture
def keyboard_calls(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """pynput.keyboard.Controller と time.sleep を差し替え、キーと待ちの呼ばれた順を 1 本の列で持つ親の Mock を返す。

    親の `controller` が Controller のインスタンス、`sleep` が time.sleep。
    """
    parent = MagicMock()
    monkeypatch.setattr(keyboard, "Controller", MagicMock(return_value=parent.controller))
    monkeypatch.setattr("time.sleep", parent.sleep)
    return parent


@pytest.fixture
def active_wm_class(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """read_active_wm_class を差し替えた Mock を返す（既定はアクティブなウィンドウの WM_CLASS を読めない）。"""
    from voice_paste.integrations.keyboard import sender_linux

    mock = MagicMock(return_value=())
    monkeypatch.setattr(sender_linux, "read_active_wm_class", mock)
    return mock


def test_send_paste_linux(keyboard_calls: MagicMock, active_wm_class: MagicMock) -> None:
    """端末アプリでなければ設定のキーを、主キーを vk で押して離す（正常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 準備
    active_wm_class.return_value = ("gnome-text-editor", "gnome-text-editor")

    # 実行
    send_paste_linux("<ctrl>+v")

    # 検証
    assert keyboard_calls.mock_calls == [
        call.sleep(0.1),
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press(V_KEY),
        call.controller.release(V_KEY),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_paste_linux_when_terminal(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """端末アプリなら Ctrl+Shift+V を送信する（正常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 準備
    active_wm_class.return_value = ("gnome-terminal-server", "Gnome-terminal")

    # 実行
    send_paste_linux("<ctrl>+v")

    # 検証
    assert keyboard_calls.mock_calls == [
        call.sleep(0.1),
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press(keyboard.Key.shift),
        call.controller.press(V_KEY),
        call.controller.release(V_KEY),
        call.controller.release(keyboard.Key.shift),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_paste_linux_when_class_name_matches(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """クラス名だけが一覧にあっても端末アプリとして扱う（正常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 準備（インスタンス名は一覧に無く、クラス名を小文字にすると一覧にある）
    active_wm_class.return_value = ("console-x", "org.gnome.Console")

    # 実行
    send_paste_linux("<ctrl>+v")

    # 検証
    keyboard_calls.controller.press.assert_any_call(keyboard.Key.shift)


def test_send_paste_linux_when_wm_class_unreadable(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """WM_CLASS を読めなければ設定のキーを送信する（正常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 準備
    active_wm_class.return_value = ()

    # 実行
    send_paste_linux("<ctrl>+v")

    # 検証
    keyboard_calls.controller.press.assert_any_call(keyboard.Key.ctrl)
    keyboard_calls.controller.press.assert_any_call(V_KEY)
    assert call.controller.press(keyboard.Key.shift) not in keyboard_calls.mock_calls


def test_send_paste_linux_when_no_main_key(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """主キーが 1 つ無ければキーを送信せずに DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 実行・検証
    with pytest.raises(DeliveryError, match="主キー"):
        send_paste_linux("<ctrl>")
    keyboard_calls.controller.press.assert_not_called()
    active_wm_class.assert_not_called()


def test_send_paste_linux_when_main_key_not_char(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """主キーが 1 文字でなければキーを送信せずに DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 実行・検証
    with pytest.raises(DeliveryError, match="1 文字"):
        send_paste_linux("<shift>+<insert>")
    keyboard_calls.controller.press.assert_not_called()


def test_send_paste_linux_when_press_failed(
    keyboard_calls: MagicMock, active_wm_class: MagicMock
) -> None:
    """主キーの送信で失敗しても押した修飾キーを離す（異常系）。"""
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux

    # 準備（Ctrl は押せて、主キーで失敗する）
    keyboard_calls.controller.press.side_effect = [None, RuntimeError("キーを押せない")]

    # 実行・検証
    with pytest.raises(RuntimeError, match="キーを押せない"):
        send_paste_linux("<ctrl>+v")
    keyboard_calls.controller.release.assert_any_call(keyboard.Key.ctrl)
