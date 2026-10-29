"""integrations/keyboard/sender.py（copy_to_clipboard・split_paste_key・send_paste・send_enter）の単体テスト。

pyperclip.copy・pynput.keyboard.Controller・time.sleep は Mock に差し替え、実機のクリップボードとキー入力には触れない。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pyperclip
import pytest
from pynput import keyboard

from voice_paste.shared.errors import DeliveryError


@pytest.fixture
def copy_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """pyperclip.copy を差し替えた Mock を返す。"""
    mock = MagicMock()
    monkeypatch.setattr(pyperclip, "copy", mock)
    return mock


@pytest.fixture
def keyboard_calls(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """pynput.keyboard.Controller と time.sleep を差し替え、キーと待ちの呼ばれた順を 1 本の列で持つ親の Mock を返す。

    親の `controller` が Controller のインスタンス、`sleep` が time.sleep。
    """
    parent = MagicMock()
    monkeypatch.setattr(keyboard, "Controller", MagicMock(return_value=parent.controller))
    monkeypatch.setattr("time.sleep", parent.sleep)
    return parent


# === copy_to_clipboard ===


def test_copy_to_clipboard(copy_mock: MagicMock) -> None:
    """文字をクリップボードへ書く（正常系）。"""
    from voice_paste.integrations.keyboard.sender import copy_to_clipboard

    # 実行
    copy_to_clipboard("テスト")

    # 検証
    copy_mock.assert_called_once_with("テスト")


def test_copy_to_clipboard_when_failed(copy_mock: MagicMock) -> None:
    """クリップボードへ書けなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender import copy_to_clipboard

    # 準備
    copy_mock.side_effect = pyperclip.PyperclipException("クリップボードが開けない")

    # 実行・検証
    with pytest.raises(DeliveryError):
        copy_to_clipboard("テスト")


# === split_paste_key ===


def test_split_paste_key() -> None:
    """修飾キーと主キーに分ける（正常系）。"""
    from voice_paste.integrations.keyboard.sender import split_paste_key

    # 実行
    result = split_paste_key("<ctrl>+<shift>+v")

    # 検証
    assert result == ([keyboard.Key.ctrl, keyboard.Key.shift], "v")


def test_split_paste_key_when_spaced_and_uppercase() -> None:
    """前後の空白と大文字を揃える（正常系）。"""
    from voice_paste.integrations.keyboard.sender import split_paste_key

    # 実行
    result = split_paste_key("<Ctrl> + V")

    # 検証
    assert result == ([keyboard.Key.ctrl], "v")


@pytest.mark.parametrize(
    "paste_key",
    [
        pytest.param("<ctrl>", id="modifier_only"),
        pytest.param("<ctrl>+v+c", id="two_main_keys"),
    ],
)
def test_split_paste_key_when_no_main_key(paste_key: str) -> None:
    """主キーが 1 つ無ければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender import split_paste_key

    # 実行・検証
    with pytest.raises(DeliveryError, match="主キー"):
        split_paste_key(paste_key)


# === send_paste ===


def test_send_paste(keyboard_calls: MagicMock) -> None:
    """設定の貼り付けのキーを、フォーカスが落ち着くのを待ってから送信する（正常系）。"""
    from voice_paste.integrations.keyboard.sender import send_paste

    # 実行
    send_paste("<ctrl>+v")

    # 検証
    assert keyboard_calls.mock_calls == [
        call.sleep(0.1),
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press("v"),
        call.controller.release("v"),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_paste_when_multiple_modifiers(keyboard_calls: MagicMock) -> None:
    """修飾キーが複数でも、押した順の逆に離す（正常系）。"""
    from voice_paste.integrations.keyboard.sender import send_paste

    # 実行
    send_paste("<ctrl>+<shift>+v")

    # 検証
    assert keyboard_calls.mock_calls == [
        call.sleep(0.1),
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press(keyboard.Key.shift),
        call.controller.press("v"),
        call.controller.release("v"),
        call.controller.release(keyboard.Key.shift),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_paste_when_spaced_and_uppercase(keyboard_calls: MagicMock) -> None:
    """キーの前後の空白と大文字を揃えて、同じキーとして送信する（正常系）。"""
    from voice_paste.integrations.keyboard.sender import send_paste

    # 実行
    send_paste("<Ctrl> + V")

    # 検証
    assert keyboard_calls.mock_calls == [
        call.sleep(0.1),
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press("v"),
        call.controller.release("v"),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_paste_when_no_main_key(keyboard_calls: MagicMock) -> None:
    """主キーが 1 つ無ければ、キーを送信せずに DeliveryError にする（異常系）。"""
    from voice_paste.integrations.keyboard.sender import send_paste

    # 実行・検証
    with pytest.raises(DeliveryError):
        send_paste("<ctrl>")
    keyboard_calls.controller.press.assert_not_called()


# === send_enter ===


def test_send_enter(keyboard_calls: MagicMock) -> None:
    """修飾キーが無ければ Enter を押して離す（正常系）。"""
    from voice_paste.integrations.keyboard.sender import send_enter

    # 実行
    send_enter()

    # 検証
    assert keyboard_calls.mock_calls == [
        call.controller.press(keyboard.Key.enter),
        call.controller.release(keyboard.Key.enter),
    ]


def test_send_enter_when_modifiers(keyboard_calls: MagicMock) -> None:
    """修飾キーを Ctrl・Alt・Shift の順に押し、逆順に離す（正常系）。"""
    from voice_paste.integrations.keyboard.sender import send_enter

    # 実行（並びが違い、Shift が重なっている）
    send_enter(("shift", "ctrl", "shift"))

    # 検証
    assert keyboard_calls.mock_calls == [
        call.controller.press(keyboard.Key.ctrl),
        call.controller.press(keyboard.Key.shift),
        call.controller.press(keyboard.Key.enter),
        call.controller.release(keyboard.Key.enter),
        call.controller.release(keyboard.Key.shift),
        call.controller.release(keyboard.Key.ctrl),
    ]


def test_send_enter_when_press_failed(keyboard_calls: MagicMock) -> None:
    """途中で失敗しても押した修飾キーを離す（異常系）。"""
    from voice_paste.integrations.keyboard.sender import send_enter

    # 準備（Ctrl は押せて、Enter で失敗する）
    keyboard_calls.controller.press.side_effect = [None, RuntimeError("キーを押せない")]

    # 実行・検証
    with pytest.raises(RuntimeError, match="キーを押せない"):
        send_enter(("ctrl",))
    keyboard_calls.controller.release.assert_any_call(keyboard.Key.ctrl)
