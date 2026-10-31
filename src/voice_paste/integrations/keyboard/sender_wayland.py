"""Linux の Wayland のセッションの貼り付けのキーと Enter の送信。python-evdev の UInput の仮想キーボードから送信する。

Wayland のセッションでは pynput・XTEST のキーがネイティブのアプリへ届かないため、カーネルの uinput で入力の機器を作ってキーを送信する。
`/dev/uinput` を開く権限（udev の規則と `input` グループ）が要り、無ければ open が DeliveryError を送出する。
"""

from __future__ import annotations

import ast
import contextlib
import json
import subprocess
import logging
import threading
import time
from collections.abc import Sequence

from evdev import UInput, UInputError, ecodes

from voice_paste.integrations.keyboard.sender import (
    ENTER_MODIFIER_KEYS,
    FOCUS_SETTLE_SEC,
    split_paste_key,
)
from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import EnterModifier

logger = logging.getLogger(__name__)

DEVICE_READY_SEC: float = 0.3
"""仮想キーボードを作ってから、コンポジターが入力の機器として受け付けるまで待つ秒数（PoC で測った値）。"""

EVDEV_MODIFIER_CODES: dict[str, int] = {
    "ctrl": ecodes.KEY_LEFTCTRL,
    "shift": ecodes.KEY_LEFTSHIFT,
    "alt": ecodes.KEY_LEFTALT,
    "cmd": ecodes.KEY_LEFTMETA,
}
"""pynput の書式の修飾キーの名前と、evdev のキーコードの対応。"""

VIRTUAL_KEYBOARD_NAME: str = "voice-paste-keyboard"
"""UInput の機器の名前。入力の機器の一覧で常駐サービスのものと見分ける。"""

KEY_DOWN: int = 1
"""EV_KEY の値で、キーを押す。"""

KEY_UP: int = 0
"""EV_KEY の値で、キーを離す。"""

NOT_OPENED_MESSAGE: str = "貼り付けのキーを送信できません。起こした文字はクリップボードにあります"
"""仮想キーボードを開いていないときの DeliveryError の理由。"""


POC_TERMINAL_NAMES: frozenset[str] = frozenset(
    {"gnome-terminal-server", "gnome-terminal", "org.gnome.terminal", "kgx", "org.gnome.console", "ptyxis", "org.gnome.ptyxis"}
)
"""PoC #223: 端末アプリと見なす名前（小文字）。拡張が返す値を記録してから決める。"""


def poc_read_focused_window() -> tuple[str, ...]:
    """PoC #223: Focused Window D-Bus の拡張から、フォーカスしているウィンドウの wm_class と wm_class_instance を読む。読めなければ空。"""
    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 引数は固定
            [
                "gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/shell/extensions/FocusedWindow",
                "--method", "org.gnome.shell.extensions.FocusedWindow.Get",
            ],
            capture_output=True, text=True, timeout=1.0, check=True,
        )
        raw = ast.literal_eval(completed.stdout.strip())[0]
        window = json.loads(raw)
    except (OSError, subprocess.SubprocessError, ValueError, SyntaxError) as error:
        logger.info(f"PoC: フォーカスしているウィンドウを読めなかった（{error}・{time.perf_counter() - started:.3f} 秒）")
        return ()
    names = tuple(str(window.get(key)) for key in ("wm_class", "wm_class_instance") if window.get(key))
    logger.info(
        f"PoC: フォーカスしているウィンドウ wm_class={window.get('wm_class')!r} "
        f"wm_class_instance={window.get('wm_class_instance')!r} title={window.get('title')!r} "
        f"（{time.perf_counter() - started:.3f} 秒）"
    )
    return names


class UInputKeyboard:
    """uinput の仮想キーボードを持ち、貼り付けのキーと Enter を送信する。起動のときに 1 回開き、終了のときに閉じる。"""

    def __init__(self) -> None:
        """仮想キーボードはまだ開かない。"""
        self._device: UInput | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        """仮想キーボードを作り、コンポジターが入力の機器として受け付けるまで待つ。開いていれば何もしない。"""
        with self._lock:
            # 開いているか
            if self._device is not None:
                # はい: 何もしない
                return
            try:
                self._device = UInput(name=VIRTUAL_KEYBOARD_NAME)
            except (OSError, UInputError) as error:
                # `/dev/uinput` を開く権限が無い・uinput が無い
                raise DeliveryError(f"キーの送信の機器を開けません（{error}）") from error
            time.sleep(DEVICE_READY_SEC)
            logger.info("仮想キーボードを開いた")

    def send_paste(self, paste_key: str) -> None:
        """設定の貼り付けのキーを、フォーカスが落ち着くのを待ってから仮想キーボードで送信する。"""
        # 1. 開いていなければ断る
        with self._lock:
            device = self._opened_device()

            # 2. 貼り付けのキーを修飾キーと主キーに分け、キーコードに替える
            modifiers, main_key = split_paste_key(paste_key)
            if len(main_key) != 1:
                raise DeliveryError(f"貼り付けのキーの主キーは 1 文字にしてください（{paste_key}）")
            modifier_codes = [EVDEV_MODIFIER_CODES[modifier.name] for modifier in modifiers]
            main_code = ecodes.ecodes.get(f"KEY_{main_key.upper()}")
            if main_code is None:
                raise DeliveryError(f"貼り付けのキーの主キーを送信できません（{paste_key}）")

            # 3. 貼り付け先のフォーカスが落ち着くのを待ってから送信する
            time.sleep(FOCUS_SETTLE_SEC)
            # PoC #223: 端末アプリなら Ctrl+Shift+V に替える
            names = poc_read_focused_window()
            if any(name.lower() in POC_TERMINAL_NAMES for name in names):
                modifier_codes = [ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT]
                main_code = ecodes.KEY_V
                paste_key = "<ctrl>+<shift>+v"
            self._press(device, modifier_codes, main_code)
        logger.info(f"貼り付けのキーを送信した（{paste_key}、uinput）")

    def send_enter(self, modifiers: Sequence[EnterModifier] = ()) -> None:
        """渡した修飾キーを押したまま Enter を仮想キーボードで送信する。待ちは呼ぶ側が置く。"""
        with self._lock:
            # 1. 開いていなければ断る
            device = self._opened_device()

            # 2. 修飾キーを Ctrl・Alt・Shift の並びに揃え、重なりを除いてキーコードに替える
            ordered = [modifier for modifier in ENTER_MODIFIER_KEYS if modifier in modifiers]
            modifier_codes = [EVDEV_MODIFIER_CODES[modifier] for modifier in ordered]

            # 3. 修飾キーを押したまま Enter を送信する
            self._press(device, modifier_codes, ecodes.KEY_ENTER)
        logger.info(f"Enter を送信した（修飾キー: {'+'.join(ordered) or 'なし'}、uinput）")

    def close(self) -> None:
        """仮想キーボードを閉じる。開いていなければ何もしない（2 回呼んでもよい）。"""
        with self._lock:
            # 開いているか
            if self._device is None:
                # いいえ: 何もしない
                return
            self._device.close()
            self._device = None

    def _opened_device(self) -> UInput:
        """開いている仮想キーボードを返す。開いていなければ DeliveryError（ロックを取った中で呼ぶ）。"""
        if self._device is None:
            raise DeliveryError(NOT_OPENED_MESSAGE)
        return self._device

    @staticmethod
    def _press(device: UInput, modifier_codes: list[int], main_code: int) -> None:
        """修飾キーを順に押し、主キーを押して離し、修飾キーを逆順に離してから確定する。書き込めなければ押したキーを離して DeliveryError にする。"""
        pressed: list[int] = []
        try:
            for code in modifier_codes:
                device.write(ecodes.EV_KEY, code, KEY_DOWN)
                pressed.append(code)
            device.write(ecodes.EV_KEY, main_code, KEY_DOWN)
            device.write(ecodes.EV_KEY, main_code, KEY_UP)
            for code in reversed(pressed):
                device.write(ecodes.EV_KEY, code, KEY_UP)
            pressed.clear()
            device.syn()
        except OSError as error:
            # 途中で失敗しても、押した修飾キーは離す（押されたままにしない）
            with contextlib.suppress(OSError):
                for code in reversed(pressed):
                    device.write(ecodes.EV_KEY, code, KEY_UP)
                device.syn()
            raise DeliveryError(f"キーを送信できません（{error}）") from error
