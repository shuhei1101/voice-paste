"""integrations/keyboard/sender_wayland.py（UInputKeyboard の open・send_paste・send_enter・close）の単体テスト。

evdev.UInput・time.sleep は Mock に差し替え、実物の `/dev/uinput` には触れない。
フォーカスしているウィンドウの wm_class（read_focused_wm_class）も Mock に差し替え、拡張は呼ばない。
キーの並びは UInput.write の呼び出しの並びで確かめる。
evdev は Linux だけの依存のため、Windows では流さない。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call

import pytest

from voice_paste.shared.errors import DeliveryError

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="evdev は Linux だけの依存のため Windows では流さない"
)

DEVICE_READY_SEC = 0.3
"""仮想キーボードを作ってから待つ秒数。"""

FOCUS_SETTLE_SEC = 0.1
"""貼り付けのキーを送信する前の待ち。"""

EDITOR_WM_CLASS = ("org.gnome.TextEditor", "org.gnome.TextEditor")
"""既定でフォーカスしているウィンドウ（端末アプリでない GNOME テキストエディター）の wm_class。"""


@pytest.fixture
def uinput(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """evdev.UInput と time.sleep を差し替え、呼ばれた順を 1 本の列で持つ親の Mock を返す。

    親の `uinput_class` が UInput のクラス、`device` がそのインスタンス、`sleep` が time.sleep。
    """
    import evdev

    from voice_paste.integrations.keyboard import sender_wayland

    parent = MagicMock()
    parent.uinput_class.return_value = parent.device
    monkeypatch.setattr(evdev, "UInput", parent.uinput_class)
    monkeypatch.setattr(sender_wayland, "UInput", parent.uinput_class, raising=False)
    monkeypatch.setattr("time.sleep", parent.sleep)
    return parent


@pytest.fixture
def focused_wm_class(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """sender_wayland が呼ぶ read_focused_wm_class を差し替えた Mock を返す。既定は端末アプリでないウィンドウ。"""
    from voice_paste.integrations.keyboard import sender_wayland

    mock = MagicMock(return_value=EDITOR_WM_CLASS)
    monkeypatch.setattr(sender_wayland, "read_focused_wm_class", mock, raising=False)
    return mock


def _key(code: int, value: int) -> object:
    """仮想キーボードへ EV_KEY を書く呼び出し（value は 1 が押す、0 が離す）。"""
    from evdev import ecodes

    return call.device.write(ecodes.EV_KEY, code, value)


def _write(code: int, value: int) -> object:
    """UInput.write へ EV_KEY を書いた呼び出しの引数（value は 1 が押す、0 が離す）。"""
    from evdev import ecodes

    return call(ecodes.EV_KEY, code, value)


# === UInputKeyboard.open ===


def test_open(uinput: MagicMock) -> None:
    """仮想キーボードを作って待つ（正常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()

    # 実行
    keyboard.open()
    keyboard.open()

    # 検証
    assert uinput.mock_calls == [
        call.uinput_class(name="voice-paste-keyboard"),
        call.sleep(DEVICE_READY_SEC),
    ]


def test_open_when_permission_denied(uinput: MagicMock) -> None:
    """開けなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    uinput.uinput_class.side_effect = PermissionError("Permission denied")
    keyboard = UInputKeyboard()

    # 実行・検証
    with pytest.raises(DeliveryError, match="Permission denied"):
        keyboard.open()


# === UInputKeyboard.send_paste ===


@pytest.mark.usefixtures("focused_wm_class")
def test_send_paste(uinput: MagicMock) -> None:
    """待ってから修飾キーと主キーを順に押して離す（正常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()
    keyboard.open()
    uinput.reset_mock()

    # 実行
    keyboard.send_paste("<ctrl>+v")

    # 検証
    assert uinput.mock_calls == [
        call.sleep(FOCUS_SETTLE_SEC),
        _key(ecodes.KEY_LEFTCTRL, 1),
        _key(ecodes.KEY_V, 1),
        _key(ecodes.KEY_V, 0),
        _key(ecodes.KEY_LEFTCTRL, 0),
        call.device.syn(),
    ]


def test_send_paste_when_terminal(uinput: MagicMock, focused_wm_class: MagicMock) -> None:
    """端末アプリなら Ctrl+Shift+V を送信する（正常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    focused_wm_class.return_value = ("gnome-terminal-server", "gnome-terminal-server")
    keyboard = UInputKeyboard()
    keyboard.open()
    uinput.reset_mock()

    # 実行
    keyboard.send_paste("<ctrl>+v")

    # 検証
    assert uinput.device.write.call_args_list == [
        _write(ecodes.KEY_LEFTCTRL, 1),
        _write(ecodes.KEY_LEFTSHIFT, 1),
        _write(ecodes.KEY_V, 1),
        _write(ecodes.KEY_V, 0),
        _write(ecodes.KEY_LEFTSHIFT, 0),
        _write(ecodes.KEY_LEFTCTRL, 0),
    ]


def test_send_paste_when_class_name_matches(
    uinput: MagicMock, focused_wm_class: MagicMock
) -> None:
    """クラス名だけが一覧にあっても端末アプリとして扱う（正常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    focused_wm_class.return_value = ("console-x", "org.gnome.Console")
    keyboard = UInputKeyboard()
    keyboard.open()

    # 実行
    keyboard.send_paste("<ctrl>+v")

    # 検証
    assert _key(ecodes.KEY_LEFTSHIFT, 1) in uinput.mock_calls


def test_send_paste_when_wm_class_unreadable(
    uinput: MagicMock, focused_wm_class: MagicMock
) -> None:
    """wm_class を読めなければ設定のキーを送信する（正常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    focused_wm_class.return_value = ()
    keyboard = UInputKeyboard()
    keyboard.open()
    uinput.reset_mock()

    # 実行
    keyboard.send_paste("<ctrl>+v")

    # 検証
    assert uinput.device.write.call_args_list == [
        _write(ecodes.KEY_LEFTCTRL, 1),
        _write(ecodes.KEY_V, 1),
        _write(ecodes.KEY_V, 0),
        _write(ecodes.KEY_LEFTCTRL, 0),
    ]


def test_send_paste_when_not_opened(uinput: MagicMock) -> None:
    """開いていなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()

    # 実行・検証
    with pytest.raises(DeliveryError):
        keyboard.send_paste("<ctrl>+v")
    uinput.device.write.assert_not_called()


def test_send_paste_when_unsupported_key(uinput: MagicMock) -> None:
    """1 文字でない主キーは DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()
    keyboard.open()

    # 実行・検証
    with pytest.raises(DeliveryError):
        keyboard.send_paste("<ctrl>+<insert>")
    uinput.device.write.assert_not_called()


@pytest.mark.usefixtures("focused_wm_class")
def test_send_paste_when_write_failed(uinput: MagicMock) -> None:
    """書き込めなければ押した修飾キーを離して DeliveryError にする（異常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備: 主キーを押す書き込みだけが OSError になる
    def _write(_type: int, code: int, value: int) -> None:
        """主キー v を押す書き込みで OSError を出す。"""
        if code == ecodes.KEY_V and value == 1:
            raise OSError("書き込めない")

    keyboard = UInputKeyboard()
    keyboard.open()
    uinput.device.write.side_effect = _write

    # 実行・検証
    with pytest.raises(DeliveryError):
        keyboard.send_paste("<ctrl>+v")
    assert _key(ecodes.KEY_LEFTCTRL, 0) in uinput.mock_calls


# === UInputKeyboard.send_enter ===


def test_send_enter_when_modifiers(uinput: MagicMock) -> None:
    """修飾キーを Ctrl・Alt・Shift の順に押し、逆順に離す（正常系）。"""
    from evdev import ecodes

    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()
    keyboard.open()
    uinput.reset_mock()

    # 実行: 並びと重なりは問わない
    keyboard.send_enter(("shift", "ctrl", "shift"))

    # 検証
    assert uinput.mock_calls == [
        _key(ecodes.KEY_LEFTCTRL, 1),
        _key(ecodes.KEY_LEFTSHIFT, 1),
        _key(ecodes.KEY_ENTER, 1),
        _key(ecodes.KEY_ENTER, 0),
        _key(ecodes.KEY_LEFTSHIFT, 0),
        _key(ecodes.KEY_LEFTCTRL, 0),
        call.device.syn(),
    ]


def test_send_enter_when_not_opened(uinput: MagicMock) -> None:
    """開いていなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()

    # 実行・検証
    with pytest.raises(DeliveryError):
        keyboard.send_enter()
    uinput.device.write.assert_not_called()


# === UInputKeyboard.close ===


def test_close(uinput: MagicMock) -> None:
    """閉じた後は送信できず、2 回目は何もしない（正常系）。"""
    from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

    # 準備
    keyboard = UInputKeyboard()
    keyboard.open()

    # 実行
    keyboard.close()
    keyboard.close()

    # 検証
    uinput.device.close.assert_called_once()
    with pytest.raises(DeliveryError):
        keyboard.send_enter()
