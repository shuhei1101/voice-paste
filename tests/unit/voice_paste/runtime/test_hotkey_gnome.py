"""runtime/hotkey_gnome.py（GnomeShortcutListener の start・stop、to_gnome_accelerator、validate_gnome_hotkeys）の単体テスト。

gsettings は subprocess.run を偽物に差し替えて確かめる。
偽物は gsettings の状態（カスタムショートカットのパスの一覧と、ショートカットごとの name・command・binding）を持ち、
一覧と値を書いた順を覚える。実物の GNOME のショートカットは検証環境の VM での通しの確認で確かめる。
Linux の実装を読み込むため、Windows では流さない。
"""

from __future__ import annotations

import ast
import logging
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Linux 専用の実装を読み込むため Windows では流さない"
)

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEYBINDING_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voice-paste-"
USER_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
"""ユーザーが自分で作ったカスタムショートカットのパス。"""

START_KEY = "<cmd>+<alt>+d"
PASTE_KEY = "<cmd>+<alt>+v"


class FakeGsettings:
    """subprocess.run で呼ばれる gsettings の偽物。

    カスタムショートカットのパスの一覧（custom-keybindings）と、`{スキーマ}:{パス}` ごとの値を持つ。
    一覧を書いた順と、値を書いた順を覚える。
    fail_on に (パスの末尾の番号と `/`, キー) を渡すと、その値を書くときに CalledProcessError を出す。
    not_found が True の間は、gsettings が見つからない（FileNotFoundError）状態を表す。
    """

    def __init__(self, paths: list[str]) -> None:
        self.paths = list(paths)
        self.values: dict[tuple[str, str], str] = {}
        self.path_writes: list[list[str]] = []
        self.value_writes: list[tuple[str, str, str]] = []
        self.fail_on: tuple[str, str] | None = None
        self.not_found = False

    def __call__(self, args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        """gsettings の get・set を受ける。"""
        if self.not_found:
            raise FileNotFoundError("gsettings")
        assert Path(args[0]).name == "gsettings"
        verb, schema, key = args[1], args[2], args[3]
        if verb == "get":
            return subprocess.CompletedProcess(args, 0, stdout=self._format_paths(), stderr="")
        value = _strip_quotes(args[4])
        if schema == MEDIA_KEYS_SCHEMA and key == "custom-keybindings":
            self.paths = _parse_paths(value)
            self.path_writes.append(list(self.paths))
        else:
            if self.fail_on == (schema.rsplit("-", 1)[-1], key):
                raise subprocess.CalledProcessError(1, args, stderr="gsettings failed")
            self.values[(schema, key)] = value
            self.value_writes.append((schema, key, value))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def _format_paths(self) -> str:
        """パスの一覧を gsettings の出力の書式にする（空なら `@as []`）。"""
        return str(self.paths) if self.paths else "@as []"

    def value_of(self, index: int, key: str) -> str:
        """番号 index の常駐サービスのショートカットに書かれた key の値を返す。"""
        return self.values[(f"{CUSTOM_KEYBINDING_SCHEMA}:{PATH_PREFIX}{index}/", key)]


def _strip_quotes(value: str) -> str:
    """gsettings に渡された値の前後の一重引用符を外す（引用符の有無はどちらも受け付ける）。"""
    return value[1:-1] if len(value) >= 2 and value[0] == "'" and value[-1] == "'" else value


def _parse_paths(value: str) -> list[str]:
    """gsettings の書式のパスの一覧を読む（`@as []` と `['a', 'b']`）。"""
    return ast.literal_eval(value.removeprefix("@as ").strip())


@pytest.fixture
def gsettings(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], FakeGsettings]:
    """subprocess.run を gsettings の偽物に差し替える関数を返す。引数は始めのパスの一覧。"""

    def _install(paths: list[str]) -> FakeGsettings:
        """偽物を作って差し替え、返す。"""
        fake = FakeGsettings(paths)
        monkeypatch.setattr("subprocess.run", fake)
        return fake

    return _install


class CountingHandler:
    """呼ばれた回数を覚える関数。raise_first が True なら、1 回目だけ例外を出す。"""

    def __init__(self, *, raise_first: bool = False) -> None:
        self.count = 0
        self._raise_first = raise_first

    def __call__(self) -> None:
        """呼ばれた回数を 1 増やす。"""
        self.count += 1
        if self._raise_first and self.count == 1:
            raise RuntimeError("関数の失敗")


# === GnomeShortcutListener.start ===


def test_start(unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]) -> None:
    """ホットキーごとにショートカットを登録し、ユーザーの登録を残す（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備
    fake = gsettings([USER_PATH])
    listener = GnomeShortcutListener(unique_name, MagicMock())

    # 実行
    listener.start({START_KEY: CountingHandler(), PASTE_KEY: CountingHandler()})

    # 検証
    assert fake.value_of(0, "binding") == "<Super><Alt>d"
    assert fake.value_of(1, "binding") == "<Super><Alt>v"
    assert shlex.split(fake.value_of(0, "command")) == [
        sys.executable,
        "-m",
        "voice_paste.runtime.send_hotkey",
        unique_name,
        START_KEY,
    ]
    assert shlex.split(fake.value_of(1, "command"))[-1] == PASTE_KEY
    assert fake.paths == [USER_PATH, f"{PATH_PREFIX}0/", f"{PATH_PREFIX}1/"]


def test_start_when_leftover(
    unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]
) -> None:
    """前の起動の登録の残りを外してから登録する（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備: 前の起動の登録が 3 つ残っている
    fake = gsettings([USER_PATH, f"{PATH_PREFIX}0/", f"{PATH_PREFIX}1/", f"{PATH_PREFIX}2/"])
    listener = GnomeShortcutListener(unique_name, MagicMock())

    # 実行
    listener.start({START_KEY: CountingHandler()})

    # 検証
    assert fake.path_writes[-1] == [USER_PATH, f"{PATH_PREFIX}0/"]


def test_start_when_dispatched(
    unique_name: str,
    gsettings: Callable[[list[str]], FakeGsettings],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """受けたホットキーの関数を呼び、例外で受付を止めない（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備: 登録した関数は 1 回目に例外を出す。排他の on_hotkey に渡された関数が、押されたホットキーを受ける
    caplog.set_level(logging.ERROR)
    gsettings([USER_PATH])
    lock = MagicMock()
    handler = CountingHandler(raise_first=True)
    listener = GnomeShortcutListener(unique_name, lock)
    listener.start({START_KEY: handler})
    dispatch = lock.on_hotkey.call_args.args[0]

    # 実行: 登録したホットキーで 2 回、登録していないホットキーで 1 回
    dispatch(START_KEY)
    errors_after_first_call = [r for r in caplog.records if r.levelno == logging.ERROR]
    dispatch(START_KEY)
    dispatch("<cmd>+<alt>+x")

    # 検証
    assert handler.count == 2
    assert len(errors_after_first_call) == 1


def test_start_when_unsupported_key(
    unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]
) -> None:
    """替えられないキーは登録を変えずに断る（異常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener
    from voice_paste.shared.errors import HotkeyError

    # 準備
    fake = gsettings([USER_PATH])
    listener = GnomeShortcutListener(unique_name, MagicMock())

    # 実行・検証
    with pytest.raises(HotkeyError):
        listener.start({"<cmd>+<alt>+<page_up>": CountingHandler()})
    assert fake.value_writes == []
    assert fake.path_writes == []


def test_start_when_gsettings_failed(
    unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]
) -> None:
    """gsettings で登録できなければ書いた登録を外して断る（異常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener
    from voice_paste.shared.errors import HotkeyError

    # 準備: 2 つ目のショートカットの binding を書くときに失敗する
    fake = gsettings([USER_PATH])
    fake.fail_on = ("1/", "binding")
    listener = GnomeShortcutListener(unique_name, MagicMock())

    # 実行・検証
    with pytest.raises(HotkeyError):
        listener.start({START_KEY: CountingHandler(), PASTE_KEY: CountingHandler()})
    assert fake.paths == [USER_PATH]


# === GnomeShortcutListener.stop ===


def test_stop(unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]) -> None:
    """常駐サービスの登録を外し、ユーザーの登録を残す（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備
    fake = gsettings([USER_PATH])
    lock = MagicMock()
    handler = CountingHandler()
    listener = GnomeShortcutListener(unique_name, lock)
    listener.start({START_KEY: handler})
    dispatch = lock.on_hotkey.call_args.args[0]
    fake.path_writes.clear()

    # 実行: 2 回止めてから、止めた後に受けたホットキーを渡す
    listener.stop()
    listener.stop()
    dispatch(START_KEY)

    # 検証
    assert fake.path_writes == [[USER_PATH]]
    assert handler.count == 0


def test_stop_when_gsettings_failed(
    unique_name: str,
    gsettings: Callable[[list[str]], FakeGsettings],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """外せなくても例外を出さない（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備: 始めた後、gsettings が見つからない状態にする
    caplog.set_level(logging.WARNING)
    fake = gsettings([USER_PATH])
    listener = GnomeShortcutListener(unique_name, MagicMock())
    listener.start({START_KEY: CountingHandler()})
    fake.not_found = True

    # 実行
    listener.stop()

    # 検証
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# === to_gnome_accelerator ===


def test_to_gnome_accelerator() -> None:
    """修飾キーと 1 文字の主キーを替える（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import to_gnome_accelerator

    # 実行
    super_alt = to_gnome_accelerator("<cmd>+<alt>+d")
    ctrl_shift = to_gnome_accelerator("<ctrl>+<shift>+v")

    # 検証
    assert super_alt == "<Super><Alt>d"
    assert ctrl_shift == "<Control><Shift>v"


def test_to_gnome_accelerator_when_function_key() -> None:
    """ファンクションキーを替える（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import to_gnome_accelerator

    # 実行
    accelerator = to_gnome_accelerator("<ctrl>+<f9>")

    # 検証
    assert accelerator == "<Control>F9"


def test_to_gnome_accelerator_when_unsupported() -> None:
    """替えられないキーは ValueError にする（異常系）。"""
    from voice_paste.runtime.hotkey_gnome import to_gnome_accelerator

    # 実行・検証
    with pytest.raises(ValueError, match="page_up"):
        to_gnome_accelerator("<cmd>+<page_up>")


# === validate_gnome_hotkeys ===


def test_validate_gnome_hotkeys() -> None:
    """替えられるホットキーは通す（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import validate_gnome_hotkeys

    # 実行・検証（例外が出ない）
    validate_gnome_hotkeys(["<cmd>+<alt>+d", "<ctrl>+<f9>"])


def test_validate_gnome_hotkeys_when_unsupported() -> None:
    """pynput は読めるが替えられないキーを断る（異常系）。"""
    from voice_paste.runtime.hotkey_gnome import validate_gnome_hotkeys
    from voice_paste.shared.errors import HotkeyError

    # 実行・検証
    with pytest.raises(HotkeyError, match=r"<ctrl>\+<page_up>"):
        validate_gnome_hotkeys(["<ctrl>+<page_up>"])


# === GnomeShortcutListener.set_suspended ===


def test_set_suspended(unique_name: str, gsettings: Callable[[list[str]], FakeGsettings]) -> None:
    """伝えない間は登録を外し、戻すと同じ組で登録し直す（正常系）。"""
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener

    # 準備
    fake = gsettings([USER_PATH])
    listener = GnomeShortcutListener(unique_name, MagicMock())
    listener.start({START_KEY: CountingHandler()})

    # 実行
    listener.set_suspended(True)
    paths_while_suspended = list(fake.paths)
    listener.set_suspended(False)

    # 検証
    assert paths_while_suspended == [USER_PATH]
    assert fake.paths == [USER_PATH, f"{PATH_PREFIX}0/"]
    assert fake.value_of(0, "binding") == "<Super><Alt>d"
