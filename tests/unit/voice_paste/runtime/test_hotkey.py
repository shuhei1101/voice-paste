"""runtime/hotkey.py（HotkeyListener の start・stop、validate_hotkeys）の単体テスト。

pynput の GlobalHotKeys は、受付を始めずに登録と開始・停止の呼び出しだけを覚える偽物に差し替える。
書式を読めないことの確かめは、本物の pynput の読み取りで行う。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import pytest
from pynput import keyboard

START_KEY = "<ctrl>+<alt>+d"
INVALID_KEY = "<ctrl>+<nokey>"


class FakeGlobalHotKeys:
    """pynput.keyboard.GlobalHotKeys の偽物。登録された組と、start・stop・join の呼ばれた順を覚える。"""

    def __init__(self, hotkeys: dict[str, Callable[[], None]]) -> None:
        self.hotkeys = hotkeys
        self.calls: list[str] = []

    def start(self) -> None:
        """受付を始めたことを覚える。"""
        self.calls.append("start")

    def stop(self) -> None:
        """受付を止めたことを覚える。"""
        self.calls.append("stop")

    def join(self, timeout: float | None = None) -> None:
        """スレッドの終わりを待ったことを覚える。"""
        self.calls.append("join")


@pytest.fixture
def listeners(monkeypatch: pytest.MonkeyPatch) -> list[FakeGlobalHotKeys]:
    """GlobalHotKeys を偽物に差し替え、作られた偽物を作られた順に並べたリストを返す。"""
    created: list[FakeGlobalHotKeys] = []

    def _factory(hotkeys: dict[str, Callable[[], None]]) -> FakeGlobalHotKeys:
        """偽物を作って控える。"""
        fake = FakeGlobalHotKeys(hotkeys)
        created.append(fake)
        return fake

    monkeypatch.setattr("pynput.keyboard.GlobalHotKeys", _factory)
    return created


class FakeListener:
    """pynput.keyboard.Listener の偽物。on_press・on_release と、start・stop・join の呼ばれた順を覚える。"""

    def __init__(
        self,
        on_press: Callable[[keyboard.Key | keyboard.KeyCode | None], None],
        on_release: Callable[[keyboard.Key | keyboard.KeyCode | None], None],
    ) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.calls: list[str] = []

    def canonical(self, key: keyboard.Key | keyboard.KeyCode | None) -> keyboard.Key | keyboard.KeyCode | None:
        """受けたキーをそのまま返す。"""
        return key

    def start(self) -> None:
        """受付を始めたことを覚える。"""
        self.calls.append("start")

    def stop(self) -> None:
        """受付を止めたことを覚える。"""
        self.calls.append("stop")

    def join(self, timeout: float | None = None) -> None:
        """スレッドの終わりを待ったことを覚える。"""
        self.calls.append("join")


class CountingHandler:
    """呼ばれた回数を覚える関数。raise_always が True なら、呼ばれるたびに例外を出す。"""

    def __init__(self, *, raise_always: bool = False) -> None:
        self.count = 0
        self._raise_always = raise_always

    def __call__(self) -> None:
        """呼ばれた回数を 1 増やす。"""
        self.count += 1
        if self._raise_always:
            raise RuntimeError("関数の失敗")


# === HotkeyListener.start ===


def test_start(listeners: list[FakeGlobalHotKeys]) -> None:
    """登録したホットキーで関数を呼ぶ（正常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener

    # 準備
    handler = CountingHandler()
    listener = HotkeyListener()

    # 実行
    listener.start({START_KEY: handler})
    listeners[0].hotkeys[START_KEY]()

    # 検証
    assert handler.count == 1
    assert listeners[0].calls == ["start"]


def test_start_when_accept_injected(
    listeners: list[FakeGlobalHotKeys], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ソフトウェアで送ったキーも受ける設定では、Listener でキーを受けて関数を呼び、GlobalHotKeys は作らない（正常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener

    # 準備
    plain_listeners: list[FakeListener] = []

    def _factory(
        on_press: Callable[[keyboard.Key | keyboard.KeyCode | None], None],
        on_release: Callable[[keyboard.Key | keyboard.KeyCode | None], None],
    ) -> FakeListener:
        """偽物を作って控える。"""
        fake = FakeListener(on_press, on_release)
        plain_listeners.append(fake)
        return fake

    monkeypatch.setattr("pynput.keyboard.Listener", _factory)
    handler = CountingHandler()
    listener = HotkeyListener(accept_injected=True)

    # 実行
    listener.start({START_KEY: handler})
    fake = plain_listeners[0]
    fake.on_press(keyboard.Key.ctrl)
    fake.on_press(keyboard.Key.alt)
    fake.on_press(keyboard.KeyCode.from_char("d"))

    # 検証
    assert handler.count == 1
    assert fake.calls == ["start"]
    assert listeners == []


def test_start_when_restarted(listeners: list[FakeGlobalHotKeys]) -> None:
    """張り直すと前の受付を止める（正常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener

    # 準備
    listener = HotkeyListener()
    listener.start({START_KEY: CountingHandler()})

    # 実行
    listener.start({START_KEY: CountingHandler()})

    # 検証
    assert len(listeners) == 2
    assert listeners[0].calls == ["start", "stop", "join"]
    assert listeners[1].calls == ["start"]


def test_start_when_handler_raised(
    listeners: list[FakeGlobalHotKeys], caplog: pytest.LogCaptureFixture
) -> None:
    """関数の例外で受付を止めない（正常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener

    # 準備
    caplog.set_level(logging.ERROR)
    handler = CountingHandler(raise_always=True)
    listener = HotkeyListener()
    listener.start({START_KEY: handler})

    # 実行
    listeners[0].hotkeys[START_KEY]()
    after_first_call = [record for record in caplog.records if record.levelno == logging.ERROR]
    listeners[0].hotkeys[START_KEY]()

    # 検証
    assert len(after_first_call) == 1
    assert handler.count == 2


def test_start_when_invalid_hotkey() -> None:
    """読めない書式は断る（異常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener
    from voice_paste.shared.errors import HotkeyError

    # 準備
    listener = HotkeyListener()

    # 実行・検証
    with pytest.raises(HotkeyError):
        listener.start({INVALID_KEY: CountingHandler()})


def test_start_when_invalid_hotkey_while_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """張り直しに失敗しても前の受付を止めない（異常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener
    from voice_paste.shared.errors import HotkeyError

    # 準備: 2 回目の生成だけが書式を読めずに ValueError を出す
    created: list[FakeGlobalHotKeys] = []

    def _factory(hotkeys: dict[str, Callable[[], None]]) -> FakeGlobalHotKeys:
        """1 回目は偽物を作り、2 回目は ValueError を出す。"""
        if created:
            raise ValueError("書式を読めない")
        fake = FakeGlobalHotKeys(hotkeys)
        created.append(fake)
        return fake

    monkeypatch.setattr("pynput.keyboard.GlobalHotKeys", _factory)
    listener = HotkeyListener()
    listener.start({START_KEY: CountingHandler()})

    # 実行・検証
    with pytest.raises(HotkeyError):
        listener.start({INVALID_KEY: CountingHandler()})
    assert created[0].calls == ["start"]


# === HotkeyListener.stop ===


def test_stop(listeners: list[FakeGlobalHotKeys]) -> None:
    """止めた後は動いていない（正常系）。"""
    from voice_paste.runtime.hotkey import HotkeyListener

    # 準備
    listener = HotkeyListener()
    listener.start({START_KEY: CountingHandler()})

    # 実行
    listener.stop()
    listener.stop()

    # 検証
    assert listeners[0].calls == ["start", "stop", "join"]


# === validate_hotkeys ===


def test_validate_hotkeys() -> None:
    """読める書式は通す（正常系）。"""
    from voice_paste.runtime.hotkey import validate_hotkeys

    # 実行・検証（例外が出ない）
    validate_hotkeys(["<ctrl>+<alt>+d", "<ctrl>+<shift>+<f5>"])


def test_validate_hotkeys_when_invalid() -> None:
    """読めない書式を断る（異常系）。"""
    from voice_paste.runtime.hotkey import validate_hotkeys
    from voice_paste.shared.errors import HotkeyError

    # 実行・検証
    with pytest.raises(HotkeyError, match=re.escape(INVALID_KEY)):
        validate_hotkeys([INVALID_KEY])
