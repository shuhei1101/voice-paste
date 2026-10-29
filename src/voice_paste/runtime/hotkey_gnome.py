"""GNOME（Wayland）のホットキーの受付。設定のホットキーを GNOME のカスタムショートカットへ登録し、押されたら配線された関数を呼ぶ。

ショートカットは、押されると send_hotkey を起動し、send_hotkey が常駐サービスの終了の依頼のソケットへホットキーを送信する。
"""

from __future__ import annotations

import ast
import logging
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from voice_paste.runtime.hotkey import _guard
from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

logger = logging.getLogger(__name__)

MEDIA_KEYS_SCHEMA: str = "org.gnome.settings-daemon.plugins.media-keys"
"""カスタムショートカットの一覧を持つ gsettings のスキーマ。"""

CUSTOM_KEYBINDING_SCHEMA: str = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
"""カスタムショートカット 1 つのスキーマ。"""

CUSTOM_KEYBINDING_PATH_PREFIX: str = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voice-paste-"
)
"""常駐サービスが登録するカスタムショートカットのパスの前半。ユーザーの登録と見分ける。"""

PYNPUT_TO_GNOME_MODIFIERS: dict[str, str] = {
    "<ctrl>": "<Control>",
    "<alt>": "<Alt>",
    "<shift>": "<Shift>",
    "<cmd>": "<Super>",
    "<win>": "<Super>",
}
"""pynput の書式の修飾キーと、GNOME のアクセラレーターの修飾キーの対応。"""


def to_gnome_accelerator(hotkey: str) -> str:
    """pynput の書式のホットキー（`<ctrl>+<alt>+r`）を GNOME のアクセラレーター（`<Control><Alt>r`）に替える。"""
    parts = hotkey.split("+")
    modifiers = "".join(PYNPUT_TO_GNOME_MODIFIERS[part] for part in parts[:-1])
    return modifiers + parts[-1]


def _gsettings(*args: str) -> str:
    """gsettings を実行し、標準出力を返す。"""
    result = subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _read_paths() -> list[str]:
    """登録されているカスタムショートカットのパスの一覧を読む。"""
    raw = _gsettings("get", MEDIA_KEYS_SCHEMA, "custom-keybindings")
    # 空の一覧は `@as []` と出る
    if raw.startswith("@as"):
        return []
    return list(ast.literal_eval(raw))


def _write_paths(paths: list[str]) -> None:
    """カスタムショートカットのパスの一覧を書く。"""
    _gsettings("set", MEDIA_KEYS_SCHEMA, "custom-keybindings", str(paths))


class GnomeShortcutListener:
    """HotkeyListener と同じ start / stop を持つ。登録したショートカットのパスと配線された関数を持つ。"""

    def __init__(self, *, name: str, lock: LinuxSingleInstanceLock) -> None:
        """排他の名前（送信のコマンドに渡す）と、ホットキーを受ける単一インスタンスの排他を受ける。"""
        self._name = name
        self._bindings: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()
        lock.on_hotkey(self._dispatch)

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """設定のホットキーを GNOME のカスタムショートカットへ登録し、受けたら関数を呼ぶ。前の登録は外す。"""
        with self._lock:
            self._unregister()
            others = [path for path in _read_paths() if not path.startswith(CUSTOM_KEYBINDING_PATH_PREFIX)]
            own: list[str] = []
            for index, hotkey in enumerate(bindings):
                path = f"{CUSTOM_KEYBINDING_PATH_PREFIX}{index}/"
                schema = f"{CUSTOM_KEYBINDING_SCHEMA}:{path}"
                command = shlex.join(
                    [sys.executable, "-m", "voice_paste.runtime.send_hotkey", self._name, hotkey]
                )
                _gsettings("set", schema, "name", f"voice-paste {hotkey}")
                _gsettings("set", schema, "command", command)
                _gsettings("set", schema, "binding", to_gnome_accelerator(hotkey))
                own.append(path)
            _write_paths(others + own)
            self._bindings = {hotkey: _guard(handler) for hotkey, handler in bindings.items()}
            logger.info(f"GNOME のショートカットを登録した（{', '.join(bindings)}）")

    def stop(self) -> None:
        """登録したショートカットを外す。"""
        with self._lock:
            self._unregister()
            self._bindings = {}

    def _unregister(self) -> None:
        """常駐サービスが登録したショートカットを一覧から外す（ロックを取った中で呼ぶ）。"""
        paths = _read_paths()
        remaining = [path for path in paths if not path.startswith(CUSTOM_KEYBINDING_PATH_PREFIX)]
        if remaining != paths:
            _write_paths(remaining)
            logger.info("GNOME のショートカットを外した")

    def _dispatch(self, hotkey: str) -> None:
        """押されたホットキーの関数を呼ぶ（呼ぶのは単一インスタンスの待つスレッド）。"""
        logger.info(f"PoC: ホットキーを受けた（{hotkey}、monotonic={time.monotonic():.3f}）")
        with self._lock:
            handler = self._bindings.get(hotkey)
        if handler is not None:
            handler()
