"""Wayland のセッションのホットキーの受付。設定のホットキーを GNOME のカスタムショートカットへ登録し、押されたら配線された関数を呼ぶ。

ショートカットのコマンドは send_hotkey を流し、send_hotkey が単一インスタンスの終了の依頼のソケットへ押されたホットキーを送信する。
登録は gsettings で行う。常駐サービスの登録はパスが CUSTOM_KEYBINDING_PATH_PREFIX で始まり、ユーザーが自分で作ったショートカットは一覧に残す。
"""

from __future__ import annotations

import ast
import logging
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from voice_paste.runtime.hotkey import validate_hotkeys
from voice_paste.shared.errors import HotkeyError

if TYPE_CHECKING:
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

logger = logging.getLogger(__name__)

MEDIA_KEYS_SCHEMA: str = "org.gnome.settings-daemon.plugins.media-keys"
"""カスタムショートカットのパスの一覧（`custom-keybindings`）を持つ gsettings のスキーマ。"""

CUSTOM_KEYBINDING_SCHEMA: str = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
"""カスタムショートカット 1 つ（name・command・binding）の gsettings のスキーマ。`{スキーマ}:{パス}` で指す。"""

CUSTOM_KEYBINDING_PATH_PREFIX: str = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voice-paste-"
)
"""常駐サービスが登録するカスタムショートカットのパスの前半。ユーザーが自分で作ったショートカットと見分ける。"""

PYNPUT_TO_GNOME_MODIFIERS: dict[str, str] = {
    "<ctrl>": "<Control>",
    "<alt>": "<Alt>",
    "<shift>": "<Shift>",
    "<cmd>": "<Super>",
}
"""pynput の書式の修飾キーと、GNOME のアクセラレーターの修飾キーの対応。"""

KEY_SEPARATOR: str = "+"
"""pynput の書式で、キーを区切る文字。"""

FUNCTION_KEY_PATTERN: re.Pattern[str] = re.compile(r"^<f([1-9]|1[0-9]|2[0-4])>$")
"""pynput の書式のファンクションキー（`<f1>`〜`<f24>`）。"""

SEND_HOTKEY_MODULE: str = "voice_paste.runtime.send_hotkey"
"""ショートカットのコマンドが流すモジュール。"""

GSETTINGS: str = "gsettings"
"""gsettings のコマンド。"""

EMPTY_PATH_LIST_PREFIX: str = "@as "
"""gsettings が空の配列に付ける型の前置き（`@as []`）。"""


def to_gnome_accelerator(hotkey: str) -> str:
    """pynput の書式のホットキー（`<cmd>+<alt>+d`）を GNOME のアクセラレーター（`<Super><Alt>d`）に替える。替えられなければ ValueError。"""
    # 1. `+` で分け、最後を主キー、それより前を修飾キーとする
    tokens = [token.strip().lower() for token in hotkey.split(KEY_SEPARATOR)]
    *modifiers, main_key = tokens

    # 2. 修飾キーを替えてつなぐ
    accelerator = ""
    for modifier in modifiers:
        # 表に無い修飾キーか
        if modifier not in PYNPUT_TO_GNOME_MODIFIERS:
            raise ValueError(f"GNOME のアクセラレーターに替えられない修飾キーです（{modifier}）")
        accelerator += PYNPUT_TO_GNOME_MODIFIERS[modifier]

    # 3. 主キーを替えて後ろにつなぐ（1 文字はそのまま、ファンクションキーは `F9` の書式）
    function_key = FUNCTION_KEY_PATTERN.match(main_key)
    if len(main_key) == 1:
        return accelerator + main_key
    if function_key is not None:
        return f"{accelerator}F{function_key.group(1)}"
    raise ValueError(f"GNOME のアクセラレーターに替えられない主キーです（{main_key}）")


def validate_gnome_hotkeys(hotkeys: Iterable[str]) -> None:
    """ホットキーを pynput が読めて、GNOME のアクセラレーターに替えられるかを、登録せずに確かめる。確かめられなければ HotkeyError。"""
    hotkey_list = list(hotkeys)
    # 1. pynput が読めるか（読めなければ HotkeyError がそのまま出る）
    validate_hotkeys(hotkey_list)

    # 2. GNOME のアクセラレーターに替えられるか
    for hotkey in hotkey_list:
        try:
            to_gnome_accelerator(hotkey)
        except ValueError as error:
            raise HotkeyError(f"GNOME のショートカットに登録できないキーです（{hotkey}）") from error


def _run_gsettings(*args: str) -> str:
    """gsettings を呼んで標準出力を返す。0 以外で終わるか見つからなければ例外（CalledProcessError・OSError）が出る。"""
    result = subprocess.run(  # noqa: S603 引数を配列で渡し、シェルを通さない
        [GSETTINGS, *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def _read_paths() -> list[str]:
    """カスタムショートカットのパスの一覧を gsettings から読む。"""
    output = _run_gsettings("get", MEDIA_KEYS_SCHEMA, "custom-keybindings").strip()
    return list(ast.literal_eval(output.removeprefix(EMPTY_PATH_LIST_PREFIX)))


def _write_paths(paths: list[str]) -> None:
    """カスタムショートカットのパスの一覧を gsettings へ書く。"""
    value = repr(paths) if paths else f"{EMPTY_PATH_LIST_PREFIX}[]"
    _run_gsettings("set", MEDIA_KEYS_SCHEMA, "custom-keybindings", value)


def _others(paths: list[str]) -> list[str]:
    """パスの一覧から、常駐サービスの登録を除いたもの（ユーザーが自分で作ったショートカット）を返す。"""
    return [path for path in paths if not path.startswith(CUSTOM_KEYBINDING_PATH_PREFIX)]


def _guard(handler: Callable[[], None]) -> Callable[[], None]:
    """単一インスタンスの待つスレッドで例外を出して受付を止めないよう、例外を握ってログに書く関数で包む。"""

    def _guarded() -> None:
        """包んだ関数を呼び、想定外の例外はログに書いて握る。"""
        try:
            handler()
        except Exception:  # noqa: BLE001 待つスレッドから漏らすと受付が止まるため
            logger.exception("ホットキーの処理で想定外の例外")

    return _guarded


class GnomeShortcutListener:
    """設定のホットキーを GNOME のカスタムショートカットへ登録し、押されたら配線された関数を呼ぶ。録音セッションは import しない。"""

    def __init__(self, name: str, lock: LinuxSingleInstanceLock) -> None:
        """排他の名前と単一インスタンスの排他を受け、排他の on_hotkey に _dispatch を渡す。登録はまだしない。"""
        self._name = name
        self._bindings: dict[str, Callable[[], None]] = {}
        self._registered = False
        self._lock = threading.Lock()
        lock.on_hotkey(self._dispatch)

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """常駐サービスの前の登録を外してから、ホットキーごとにカスタムショートカットを登録する。"""
        with self._lock:
            # 1. 各ホットキーを GNOME のアクセラレーターに替える（替えられなければ、登録を変えずに断る）
            try:
                accelerators = {hotkey: to_gnome_accelerator(hotkey) for hotkey in bindings}
            except ValueError as error:
                raise HotkeyError(str(error)) from error

            # 2. 各関数を、例外を握る関数で包む
            guarded = {hotkey: _guard(handler) for hotkey, handler in bindings.items()}

            # 3. 前の起動の残りと張り直す前の登録を外した一覧を書き戻し、ショートカットごとの値と一覧を書く
            try:
                others = _others(_read_paths())
                _write_paths(others)
                own = self._write_shortcuts(accelerators)
                _write_paths([*others, *own])
            except (subprocess.CalledProcessError, OSError) as error:
                # 書いた登録を外してから断る（押したキーを GNOME が受けてアプリへ届けない登録を残さない）
                self._remove_own()
                reason = getattr(error, "stderr", None) or error
                raise HotkeyError(f"GNOME のショートカットを登録できません（{reason}）") from error

            # 4. 包んだ関数を持つ
            self._bindings = guarded
            self._registered = True
            logger.info(f"GNOME のショートカットを登録した（{', '.join(bindings)}）")

    def stop(self) -> None:
        """常駐サービスの登録を一覧から外し、受付の関数を空にする。外せなくても送出せず WARNING のログを書く。登録が無ければ一覧を書かない。"""
        with self._lock:
            self._bindings = {}
            # 登録が無いか
            if not self._registered:
                # 無い: 一覧を書かない
                return
            self._registered = False
            self._remove_own()

    def _write_shortcuts(self, accelerators: dict[str, str]) -> list[str]:
        """ホットキーごとにショートカットの name・command・binding を書き、書いたパスを返す。"""
        paths: list[str] = []
        for index, (hotkey, accelerator) in enumerate(accelerators.items()):
            path = f"{CUSTOM_KEYBINDING_PATH_PREFIX}{index}/"
            schema = f"{CUSTOM_KEYBINDING_SCHEMA}:{path}"
            command = shlex.join([sys.executable, "-m", SEND_HOTKEY_MODULE, self._name, hotkey])
            _run_gsettings("set", schema, "name", f"voice-paste {hotkey}")
            _run_gsettings("set", schema, "command", command)
            _run_gsettings("set", schema, "binding", accelerator)
            paths.append(path)
        return paths

    @staticmethod
    def _remove_own() -> None:
        """常駐サービスの登録を一覧から外す。外せなければ WARNING のログを書く（終了の片付けと、登録の失敗の巻き戻しで呼ぶため）。"""
        try:
            _write_paths(_others(_read_paths()))
        except (subprocess.CalledProcessError, OSError) as error:
            logger.warning(f"GNOME のショートカットの登録を外せなかった（{error}）")

    def _dispatch(self, hotkey: str) -> None:
        """押されたホットキーの関数を呼ぶ。登録していないホットキーと、止めた後に受けたホットキーでは何もしない。"""
        with self._lock:
            handler = self._bindings.get(hotkey)
        if handler is not None:
            handler()
