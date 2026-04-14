"""設定ウィンドウ（tkinter GUI）モジュール。"""

import tkinter as tk
from tkinter import ttk
from typing import Callable

from pynput import keyboard as pynput_keyboard
from dotenv import set_key

import shutil
from tkinter import messagebox

from voice_paste import config
from voice_paste.constants import ROOT_DIR, RESOURCES_DIR
from voice_paste.logger import get_logger

logger = get_logger(__name__)

_ENV_FILE = str(ROOT_DIR / ".env")

# ドロップダウン選択肢
_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
_DEVICES = ["cuda", "cpu"]
_COMPUTE_TYPES = ["float16", "int8", "float32"]
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
_WINDOW_POSITIONS = ["center", "top-left", "top-right", "bottom-left", "bottom-right"]
_BOOL_OPTIONS = ["true", "false"]

# ダークテーマ色
_BG = "#1e1e1e"
_FG = "#e0e0e0"
_ENTRY_BG = "#2d2d2d"
_ACCENT = "#0078d4"
_RECORDING_BG = "#3a1e1e"

# pynput Key → 表示名マッピング
_KEY_NAMES: dict[pynput_keyboard.Key, str] = {
    pynput_keyboard.Key.ctrl_l: "ctrl",
    pynput_keyboard.Key.ctrl_r: "ctrl",
    pynput_keyboard.Key.alt_l: "alt",
    pynput_keyboard.Key.alt_r: "alt",
    pynput_keyboard.Key.shift: "shift",
    pynput_keyboard.Key.shift_l: "shift",
    pynput_keyboard.Key.shift_r: "shift",
    pynput_keyboard.Key.cmd: "cmd",
    pynput_keyboard.Key.cmd_l: "cmd",
    pynput_keyboard.Key.cmd_r: "cmd",
}

# 修飾キー一覧
_MODIFIER_KEYS = {
    pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r,
    pynput_keyboard.Key.alt_l, pynput_keyboard.Key.alt_r,
    pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l,
    pynput_keyboard.Key.shift_r,
    pynput_keyboard.Key.cmd, pynput_keyboard.Key.cmd_l,
    pynput_keyboard.Key.cmd_r,
}


class _HotkeyCapture:
    """ホットキー入力キャプチャ用ウィジェット。

    フォーカス時にキーを押すと、押下中の修飾キー+通常キーを pynput 形式の
    文字列として Entry に反映する。
    """

    def __init__(self, parent: tk.Widget, default: str, row: int) -> None:
        self._frame = tk.Frame(parent, bg=_BG)
        self._frame.grid(row=row, column=1, sticky="ew", padx=12, pady=4)

        self._entry = tk.Entry(
            self._frame, bg=_ENTRY_BG, fg=_FG, insertbackground=_FG,
            relief="flat", width=22, state="readonly",
        )
        self._entry.configure(readonlybackground=_ENTRY_BG)
        self._entry.pack(side="left", fill="x", expand=True)

        self._btn = tk.Button(
            self._frame, text="入力", bg="#3a3a3a", fg="#cccccc",
            activebackground="#555555", activeforeground="#ffffff",
            relief="flat", padx=8, cursor="hand2",
            command=self._toggle_capture,
        )
        self._btn.pack(side="left", padx=(4, 0))

        self._value = default
        self._set_display(default)

        self._capturing = False
        self._pressed_modifiers: set[str] = set()
        self._listener: pynput_keyboard.Listener | None = None

    def get(self) -> str:
        return self._value

    def _set_display(self, text: str) -> None:
        self._entry.configure(state="normal")
        self._entry.delete(0, tk.END)
        self._entry.insert(0, text)
        self._entry.configure(state="readonly")

    def _toggle_capture(self) -> None:
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self) -> None:
        self._capturing = True
        self._pressed_modifiers = set()
        self._btn.configure(text="停止", bg="#a03030")
        self._entry.configure(readonlybackground=_RECORDING_BG)
        self._set_display("キーを押してください...")

        self._listener = pynput_keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.start()

    def _stop_capture(self) -> None:
        self._capturing = False
        self._btn.configure(text="入力", bg="#3a3a3a")
        self._entry.configure(readonlybackground=_ENTRY_BG)
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_key_press(self, key: pynput_keyboard.Key | pynput_keyboard.KeyCode | None) -> None:
        if not self._capturing or key is None:
            return

        if key in _MODIFIER_KEYS:
            name = _KEY_NAMES.get(key, str(key))
            self._pressed_modifiers.add(name)
            return

        # 通常キーが押された → 修飾キー+通常キーでホットキー確定
        if isinstance(key, pynput_keyboard.KeyCode):
            # 修飾キーと同時押しだと char が None になるので vk から文字を復元
            if key.char and key.char.isprintable():
                key_name = key.char.lower()
            elif key.vk is not None:
                # vk 0x30-0x39 = '0'-'9', 0x41-0x5A = 'a'-'z'
                if 0x41 <= key.vk <= 0x5A:
                    key_name = chr(key.vk).lower()
                elif 0x30 <= key.vk <= 0x39:
                    key_name = chr(key.vk)
                else:
                    key_name = str(key.vk)
            else:
                key_name = str(key)
        else:
            key_name = key.name if hasattr(key, "name") else str(key)

        # pynput GlobalHotKeys 形式に変換: <mod1>+<mod2>+key
        parts = [f"<{m}>" for m in sorted(self._pressed_modifiers)]
        parts.append(key_name)
        hotkey_str = "+".join(parts)

        self._value = hotkey_str
        self._entry.after(0, lambda: self._set_display(hotkey_str))
        self._entry.after(0, self._stop_capture)

    def _on_key_release(self, key: pynput_keyboard.Key | pynput_keyboard.KeyCode | None) -> None:
        if key in _MODIFIER_KEYS:
            name = _KEY_NAMES.get(key, str(key))
            self._pressed_modifiers.discard(name)

    def destroy(self) -> None:
        self._stop_capture()


class SettingsWindow:
    """設定ウィンドウクラス。"""

    def __init__(
        self,
        on_save: Callable[[dict[str, str]], None],
        on_restart: Callable[[], None] | None = None,
    ) -> None:
        self._on_save = on_save
        self._on_restart = on_restart
        self._root: tk.Tk | None = None
        self._hotkey_captures: list[_HotkeyCapture] = []

    def show(self) -> None:
        """設定ウィンドウを表示する（mainloop でブロック）。"""
        self._root = tk.Tk()
        root = self._root
        root.title("voice-paste 設定")
        root.resizable(False, False)
        root.configure(bg=_BG)

        w, h = 420, 620
        sx = (root.winfo_screenwidth() - w) // 2
        sy = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{sx}+{sy}")
        root.attributes("-topmost", True)

        root.bind("<Escape>", lambda _: self._cancel())

        # --- スタイル ---
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                         fieldbackground=_ENTRY_BG,
                         background=_ENTRY_BG,
                         foreground=_FG,
                         selectbackground=_ACCENT,
                         selectforeground="#ffffff",
                         arrowcolor=_FG,
                         bordercolor=_ENTRY_BG,
                         lightcolor=_ENTRY_BG,
                         darkcolor=_ENTRY_BG)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", _ENTRY_BG)],
                  foreground=[("readonly", _FG)],
                  selectbackground=[("readonly", _ACCENT)],
                  selectforeground=[("readonly", "#ffffff")])
        # ドロップダウンリスト（Listbox）のダークテーマ
        root.option_add("*TCombobox*Listbox.background", _ENTRY_BG)
        root.option_add("*TCombobox*Listbox.foreground", _FG)
        root.option_add("*TCombobox*Listbox.selectBackground", _ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        row = 0
        pad = {"padx": 12, "pady": 4}

        def label(text: str, r: int) -> None:
            tk.Label(root, text=text, bg=_BG, fg=_FG,
                     anchor="w").grid(row=r, column=0, sticky="w", **pad)

        def combo(values: list[str], default: str, r: int) -> ttk.Combobox:
            c = ttk.Combobox(root, values=values, state="readonly",
                             style="Dark.TCombobox", width=26)
            c.set(default)
            c.grid(row=r, column=1, sticky="ew", **pad)
            return c

        def hotkey_input(default: str, r: int) -> _HotkeyCapture:
            cap = _HotkeyCapture(root, default, r)
            self._hotkey_captures.append(cap)
            return cap

        # 録音開始ホットキー
        label("録音開始:", row)
        self._hotkey = hotkey_input(config.RESIDENT_HOTKEY, row)
        row += 1

        # 録音確定ホットキー
        label("録音確定:", row)
        self._confirm_hotkey = hotkey_input(config.CONFIRM_HOTKEY, row)
        row += 1

        # 録音確定(貼付のみ)ホットキー
        label("確定(貼付のみ):", row)
        self._confirm_paste_only_hotkey = hotkey_input(config.CONFIRM_PASTE_ONLY_HOTKEY, row)
        row += 1

        # 録音キャンセルホットキー
        label("録音キャンセル:", row)
        self._cancel_hotkey = hotkey_input(config.CANCEL_HOTKEY, row)
        row += 1

        # コピーのみホットキー
        label("コピーのみ:", row)
        self._copy_only_hotkey = hotkey_input(config.COPY_ONLY_HOTKEY, row)
        row += 1

        # 貼付→送信ディレイ
        label("送信待機(秒):", row)
        self._paste_enter_delay = tk.Entry(
            root, bg=_ENTRY_BG, fg=_FG, insertbackground=_FG,
            relief="flat", width=8,
        )
        self._paste_enter_delay.insert(0, str(config.PASTE_ENTER_DELAY))
        self._paste_enter_delay.grid(row=row, column=1, sticky="w", padx=12, pady=4)
        row += 1

        # LOG_LEVEL
        label("ログレベル:", row)
        self._log_level = combo(_LOG_LEVELS, config.LOG_LEVEL, row)
        row += 1

        # セパレータ
        ttk.Separator(root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        row += 1

        # Whisper モデル
        label("Whisper モデル:", row)
        self._model = combo(_MODELS, config.WHISPER_MODEL, row)
        row += 1

        # デバイス
        label("デバイス:", row)
        self._device = combo(_DEVICES, config.WHISPER_DEVICE, row)
        row += 1

        # 量子化タイプ
        label("量子化タイプ:", row)
        self._compute = combo(_COMPUTE_TYPES, config.WHISPER_COMPUTE_TYPE, row)
        row += 1

        # 注釈
        tk.Label(root, text="(*) モデル・デバイス・量子化の変更は再起動後に反映",
                 bg=_BG, fg="#888888", font=("", 8)).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 8))
        row += 1

        # セパレータ
        ttk.Separator(root, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        row += 1

        # ウィンドウ表示位置
        label("表示位置:", row)
        self._window_position = combo(_WINDOW_POSITIONS, config.WINDOW_POSITION, row)
        row += 1

        # 常に最前面
        label("常に最前面:", row)
        self._window_topmost = combo(_BOOL_OPTIONS, str(config.WINDOW_TOPMOST).lower(), row)
        row += 1

        # カーソル位置のモニター
        label("カーソル側モニター:", row)
        self._window_follow_cursor = combo(_BOOL_OPTIONS, str(config.WINDOW_FOLLOW_CURSOR).lower(), row)
        row += 1

        # ウィンドウ非表示
        label("ウィンドウ非表示:", row)
        self._window_hidden = combo(_BOOL_OPTIONS, str(config.WINDOW_HIDDEN).lower(), row)
        row += 1

        # 波形感度
        label("波形の感度:", row)
        self._wave_gain = tk.Entry(
            root, bg=_ENTRY_BG, fg=_FG, insertbackground=_FG,
            relief="flat", width=8,
        )
        self._wave_gain.insert(0, str(config.WAVE_GAIN))
        self._wave_gain.grid(row=row, column=1, sticky="w", padx=12, pady=4)
        row += 1

        # ボタンフレーム
        btn_frame = tk.Frame(root, bg=_BG)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(4, 12))

        tk.Button(btn_frame, text="保存", bg=_ACCENT, fg="#ffffff",
                  activebackground="#005fa3", activeforeground="#ffffff",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._save).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="保存+再起動", bg="#107c10", fg="#ffffff",
                  activebackground="#0b5e0b", activeforeground="#ffffff",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._save_and_restart).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="初期化", bg="#a03030", fg="#ffffff",
                  activebackground="#cc4444", activeforeground="#ffffff",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._reset).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="キャンセル", bg="#3a3a3a", fg="#cccccc",
                  activebackground="#555555", activeforeground="#ffffff",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  command=self._cancel).pack(side="left")

        root.columnconfigure(1, weight=1)
        root.mainloop()

    def _save(self) -> None:
        """設定を .env に保存し、コールバックを呼ぶ。"""
        changed: dict[str, str] = {}

        def _check(key: str, new_val: str, old_val: str) -> None:
            if new_val != old_val:
                changed[key] = new_val

        _check("RESIDENT_HOTKEY", self._hotkey.get().strip(), config.RESIDENT_HOTKEY)
        _check("CONFIRM_HOTKEY", self._confirm_hotkey.get().strip(), config.CONFIRM_HOTKEY)
        _check("CONFIRM_PASTE_ONLY_HOTKEY", self._confirm_paste_only_hotkey.get().strip(), config.CONFIRM_PASTE_ONLY_HOTKEY)
        _check("CANCEL_HOTKEY", self._cancel_hotkey.get().strip(), config.CANCEL_HOTKEY)
        _check("COPY_ONLY_HOTKEY", self._copy_only_hotkey.get().strip(), config.COPY_ONLY_HOTKEY)
        _check("PASTE_ENTER_DELAY", self._paste_enter_delay.get().strip(), str(config.PASTE_ENTER_DELAY))
        _check("LOG_LEVEL", self._log_level.get(), config.LOG_LEVEL)
        _check("WHISPER_MODEL", self._model.get(), config.WHISPER_MODEL)
        _check("WHISPER_DEVICE", self._device.get(), config.WHISPER_DEVICE)
        _check("WHISPER_COMPUTE_TYPE", self._compute.get(), config.WHISPER_COMPUTE_TYPE)
        _check("WINDOW_POSITION", self._window_position.get(), config.WINDOW_POSITION)
        _check("WINDOW_TOPMOST", self._window_topmost.get(), str(config.WINDOW_TOPMOST).lower())
        _check("WINDOW_FOLLOW_CURSOR", self._window_follow_cursor.get(), str(config.WINDOW_FOLLOW_CURSOR).lower())
        _check("WINDOW_HIDDEN", self._window_hidden.get(), str(config.WINDOW_HIDDEN).lower())
        _check("WAVE_GAIN", self._wave_gain.get().strip(), str(config.WAVE_GAIN))

        if not changed:
            self._close()
            return

        # .env に書き込み
        for key, val in changed.items():
            set_key(_ENV_FILE, key, val)
            logger.info("Settings written: %s = %s", key, val)
        logger.info("Settings saved to .env: %s", list(changed.keys()))

        # config モジュールの値をランタイム更新（即時反映するもの）
        if "RESIDENT_HOTKEY" in changed:
            config.RESIDENT_HOTKEY = changed["RESIDENT_HOTKEY"]
        if "CONFIRM_HOTKEY" in changed:
            config.CONFIRM_HOTKEY = changed["CONFIRM_HOTKEY"]
        if "CONFIRM_PASTE_ONLY_HOTKEY" in changed:
            config.CONFIRM_PASTE_ONLY_HOTKEY = changed["CONFIRM_PASTE_ONLY_HOTKEY"]
        if "CANCEL_HOTKEY" in changed:
            config.CANCEL_HOTKEY = changed["CANCEL_HOTKEY"]
        if "COPY_ONLY_HOTKEY" in changed:
            config.COPY_ONLY_HOTKEY = changed["COPY_ONLY_HOTKEY"]
        if "PASTE_ENTER_DELAY" in changed:
            config.PASTE_ENTER_DELAY = float(changed["PASTE_ENTER_DELAY"])
        if "LOG_LEVEL" in changed:
            config.LOG_LEVEL = changed["LOG_LEVEL"]
        if "WINDOW_POSITION" in changed:
            config.WINDOW_POSITION = changed["WINDOW_POSITION"]
        if "WINDOW_TOPMOST" in changed:
            config.WINDOW_TOPMOST = changed["WINDOW_TOPMOST"].lower() == "true"
        if "WINDOW_FOLLOW_CURSOR" in changed:
            config.WINDOW_FOLLOW_CURSOR = changed["WINDOW_FOLLOW_CURSOR"].lower() == "true"
        if "WINDOW_HIDDEN" in changed:
            config.WINDOW_HIDDEN = changed["WINDOW_HIDDEN"].lower() == "true"
        if "WAVE_GAIN" in changed:
            config.WAVE_GAIN = float(changed["WAVE_GAIN"])

        self._close()
        self._on_save(changed)

    def _save_and_restart(self) -> None:
        """設定を保存してアプリを再起動する。"""
        self._save()
        # 保存後の.envを確認
        from pathlib import Path
        env_content = Path(_ENV_FILE).read_text(encoding="utf-8")
        for line in env_content.splitlines():
            if "WAVE_GAIN" in line:
                logger.info("After save, .env contains: %s", line)
        logger.info("config.WAVE_GAIN after save: %s", config.WAVE_GAIN)
        if self._on_restart:
            self._on_restart()

    def _reset(self) -> None:
        """設定を初期値に戻す（.env.sample で .env を上書き）。"""
        if not messagebox.askyesno(
            "設定の初期化",
            "すべての設定をデフォルトに戻します。\nよろしいですか？\n\n※反映には再起動が必要です",
            parent=self._root,
        ):
            return

        env_file = ROOT_DIR / ".env"
        # .env.sample を探す（ROOT_DIR → RESOURCES_DIR）
        env_sample = ROOT_DIR / ".env.sample"
        if not env_sample.exists():
            env_sample = RESOURCES_DIR.parent / ".env.sample"
        if not env_sample.exists():
            env_sample = RESOURCES_DIR / ".env.sample"

        if env_sample.exists():
            shutil.copy(env_sample, env_file)
            logger.info("Settings reset to defaults from %s", env_sample)
        else:
            logger.warning(".env.sample not found, cannot reset.")

        self._close()

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        for cap in self._hotkey_captures:
            cap.destroy()
        self._hotkey_captures.clear()
        if self._root:
            self._root.destroy()
            self._root = None
