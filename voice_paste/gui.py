"""録音モーダルウィンドウ（tkinter GUI）モジュール。"""

import ctypes
import ctypes.wintypes
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, TYPE_CHECKING, Literal

from pynput import keyboard as pynput_keyboard

if TYPE_CHECKING:
    from voice_paste.audio.recorder import AudioRecorder

from voice_paste import config
from voice_paste.logger import get_logger

logger = get_logger(__name__)

# 録音結果の種別
ConfirmMode = Literal["paste_enter", "paste_only", "copy_only"]

# 波形アニメーション設定
_WAVE_UPDATE_MS = 50       # 更新間隔（ms）
_WAVE_BAR_COUNT = 20       # バーの本数
_WAVE_BAR_WIDTH = 6        # バーの幅（px）
_WAVE_BAR_GAP = 3          # バー間隔（px）
_WAVE_MAX_HEIGHT = 160     # バーの最大高さ（px）
_WAVE_MIN_HEIGHT = 3       # バーの最小高さ（px）
_WAVE_COLOR = "#0078d4"    # バーの色
_WAVE_PAUSED_COLOR = "#555555"  # 一時停止中のバーの色

# ダークテーマ色
_BG = "#1e1e1e"
_FG = "#e0e0e0"
_ACCENT = "#0078d4"
_PAUSE_COLOR = "#e0a000"   # 一時停止ボタン（黄色系）
_RESUME_COLOR = "#0078d4"  # 再開ボタン（青）


def _get_cursor_monitor_rect() -> tuple[int, int, int, int]:
    """カーソルがあるモニターの作業領域 (x, y, w, h) を返す。"""
    try:
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

        # MONITOR_DEFAULTTONEAREST = 2
        hmon = ctypes.windll.user32.MonitorFromPoint(pt, 2)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rc = mi.rcWork
        return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
    except Exception:
        logger.warning("Failed to detect cursor monitor, falling back to primary.")
        return (0, 0, 0, 0)


def _calc_window_position(
    win_w: int,
    win_h: int,
    position: str,
    follow_cursor: bool,
    root: tk.Tk,
) -> tuple[int, int]:
    """ウィンドウの表示座標を計算する。"""
    margin = 20

    if follow_cursor:
        mon_x, mon_y, mon_w, mon_h = _get_cursor_monitor_rect()
        if mon_w == 0:
            mon_w = root.winfo_screenwidth()
            mon_h = root.winfo_screenheight()
    else:
        mon_x, mon_y = 0, 0
        mon_w = root.winfo_screenwidth()
        mon_h = root.winfo_screenheight()

    if position == "top-left":
        return (mon_x + margin, mon_y + margin)
    elif position == "top-right":
        return (mon_x + mon_w - win_w - margin, mon_y + margin)
    elif position == "bottom-left":
        return (mon_x + margin, mon_y + mon_h - win_h - margin)
    elif position == "bottom-right":
        return (mon_x + mon_w - win_w - margin, mon_y + mon_h - win_h - margin)
    else:  # center
        return (mon_x + (mon_w - win_w) // 2, mon_y + (mon_h - win_h) // 2)


class RecordingModal:
    """音声録音用モーダルウィンドウクラス。"""

    def __init__(
        self,
        on_confirm: Callable[[ConfirmMode], None],
        on_cancel: Callable[[], None],
        recorder: "AudioRecorder | None" = None,
    ) -> None:
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._recorder = recorder
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._bar_heights: list[float] = [_WAVE_MIN_HEIGHT] * _WAVE_BAR_COUNT
        self._animation_running = False
        self._hotkey_listener: pynput_keyboard.GlobalHotKeys | None = None
        self._pause_btn: tk.Button | None = None

    def show(self) -> None:
        """モーダルウィンドウを表示する。"""
        logger.info("Showing recording modal.")
        self._root = tk.Tk()
        self._root.title("voice-paste")
        self._root.resizable(False, False)

        # ウィンドウサイズを計算
        canvas_width = _WAVE_BAR_COUNT * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP) + _WAVE_BAR_GAP
        window_width = max(canvas_width + 40, 380)
        window_height = 300 + (34 if config.AI_SEND_APPS else 0)

        # ウィンドウ位置
        x, y = _calc_window_position(
            window_width, window_height,
            config.WINDOW_POSITION,
            config.WINDOW_FOLLOW_CURSOR,
            self._root,
        )
        self._root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self._root.configure(bg=_BG)
        self._root.attributes("-topmost", config.WINDOW_TOPMOST)

        # ウィンドウ非表示モード
        if config.WINDOW_HIDDEN:
            self._root.withdraw()

        # ウィンドウ閉じるボタン = キャンセル
        self._root.protocol("WM_DELETE_WINDOW", self._cancel)

        # 波形 Canvas
        self._canvas = tk.Canvas(
            self._root,
            width=canvas_width,
            height=_WAVE_MAX_HEIGHT + 10,
            bg=_BG,
            highlightthickness=0,
        )
        self._canvas.pack(pady=(14, 8))

        # 一時停止ボタンフレーム
        pause_frame = tk.Frame(self._root, bg=_BG)
        pause_frame.pack(pady=(0, 6))

        btn_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")

        self._pause_btn = tk.Button(
            pause_frame, text="⏸ 一時停止", font=btn_font,
            bg=_PAUSE_COLOR, fg="#ffffff",
            activebackground="#c08800", activeforeground="#ffffff",
            relief="flat", padx=16, pady=5, cursor="hand2",
            command=self._toggle_pause,
        )
        self._pause_btn.pack()

        # ボタンフレーム
        btn_frame = tk.Frame(self._root, bg=_BG)
        btn_frame.pack(pady=(0, 6 if config.AI_SEND_APPS else 12))

        # 貼付+送信 ボタン（青）
        tk.Button(
            btn_frame, text="貼付+送信", font=btn_font,
            bg="#0078d4", fg="#ffffff",
            activebackground="#005fa3", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=lambda: self._confirm("paste_enter"),
        ).pack(side="left", padx=(0, 6))

        # 貼付のみ ボタン（緑系）
        tk.Button(
            btn_frame, text="貼付のみ", font=btn_font,
            bg="#107c10", fg="#ffffff",
            activebackground="#0b5e0b", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=lambda: self._confirm("paste_only"),
        ).pack(side="left", padx=(0, 6))

        # コピー ボタン（グレー）
        tk.Button(
            btn_frame, text="コピー", font=btn_font,
            bg="#5c5c5c", fg="#ffffff",
            activebackground="#777777", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=lambda: self._confirm("copy_only"),
        ).pack(side="left")

        # AI送信ボタン（設定されたアプリ分だけ追加）
        if config.AI_SEND_APPS:
            ai_frame = tk.Frame(self._root, bg=_BG)
            ai_frame.pack(pady=(0, 12))
            for idx, app in enumerate(config.AI_SEND_APPS):
                mode = f"send_to_ai_{idx}"
                tk.Button(
                    ai_frame, text=app["name"], font=btn_font,
                    bg="#6b2fa0", fg="#ffffff",
                    activebackground="#4e2080", activeforeground="#ffffff",
                    relief="flat", padx=12, pady=5, cursor="hand2",
                    command=lambda m=mode: self._confirm(m),
                ).pack(side="left", padx=(0, 8))

        # キーバインド（ウィンドウフォーカス時）
        self._root.bind("<Return>", lambda _: self._confirm("paste_enter"))
        self._root.bind("<Escape>", lambda _: self._cancel())

        # グローバルホットキーで確定/キャンセル（ウィンドウ非フォーカスでも動作）
        hotkeys = {
            config.CONFIRM_HOTKEY: lambda: self._hotkey_confirm("paste_enter"),
            config.CONFIRM_PASTE_ONLY_HOTKEY: lambda: self._hotkey_confirm("paste_only"),
            config.COPY_ONLY_HOTKEY: lambda: self._hotkey_confirm("copy_only"),
            config.CANCEL_HOTKEY: self._hotkey_cancel,
        }
        if config.PAUSE_HOTKEY and config.PAUSE_HOTKEY not in hotkeys:
            hotkeys[config.PAUSE_HOTKEY] = self._hotkey_toggle_pause
        for _ai_i, _ai_app in enumerate(config.AI_SEND_APPS):
            _ai_hk = _ai_app.get("hotkey", "")
            if _ai_hk and _ai_hk not in hotkeys:
                hotkeys[_ai_hk] = lambda i=_ai_i: self._hotkey_confirm(f"send_to_ai_{i}")
        self._hotkey_listener = pynput_keyboard.GlobalHotKeys(hotkeys)
        self._hotkey_listener.start()

        # 波形アニメーション開始
        self._animation_running = True
        self._update_wave()

        self._root.mainloop()

    def _toggle_pause(self) -> None:
        """録音の一時停止/再開を切り替える。"""
        if self._recorder is None:
            return
        if self._recorder.is_paused:
            self._recorder.resume()
            if self._pause_btn:
                self._pause_btn.configure(
                    text="⏸ 一時停止",
                    bg=_PAUSE_COLOR,
                    activebackground="#c08800",
                )
            logger.info("Recording resumed by user.")
        else:
            self._recorder.pause()
            if self._pause_btn:
                self._pause_btn.configure(
                    text="▶ 再開",
                    bg=_RESUME_COLOR,
                    activebackground="#005fa3",
                )
            logger.info("Recording paused by user.")

    def _hotkey_confirm(self, mode: ConfirmMode) -> None:
        """グローバルホットキーからの確定（メインスレッドへ委譲）。"""
        if self._root:
            self._root.after(0, lambda: self._confirm(mode))

    def _hotkey_cancel(self) -> None:
        """グローバルホットキーからのキャンセル（メインスレッドへ委譲）。"""
        if self._root:
            self._root.after(0, self._cancel)

    def _hotkey_toggle_pause(self) -> None:
        """グローバルホットキーからの一時停止/再開（メインスレッドへ委譲）。"""
        if self._root:
            self._root.after(0, self._toggle_pause)

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_listener:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

    def _update_wave(self) -> None:
        """波形アニメーションを更新する。"""
        if not self._animation_running or self._canvas is None or self._root is None:
            return

        paused = self._recorder is not None and self._recorder.is_paused

        if self._recorder is not None and not paused:
            level = self._recorder.get_level()
        else:
            level = 0.0

        canvas_w = self._canvas.winfo_width() or (_WAVE_BAR_COUNT * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP))
        canvas_h = self._canvas.winfo_height() or (_WAVE_MAX_HEIGHT + 10)
        center_y = canvas_h // 2

        bar_color = _WAVE_PAUSED_COLOR if paused else _WAVE_COLOR

        import random
        self._canvas.delete("all")

        for i in range(_WAVE_BAR_COUNT):
            center_factor = 1.0 - abs(i - _WAVE_BAR_COUNT / 2) / (_WAVE_BAR_COUNT / 2) * 0.4
            noise = random.uniform(0.5, 1.5) if level > 0.01 else random.uniform(0.8, 1.2)
            target_h = max(
                _WAVE_MIN_HEIGHT,
                min(_WAVE_MAX_HEIGHT, level * _WAVE_MAX_HEIGHT * center_factor * noise * config.WAVE_GAIN),
            )
            self._bar_heights[i] = self._bar_heights[i] * 0.6 + target_h * 0.4

            bar_h = self._bar_heights[i]
            x = _WAVE_BAR_GAP + i * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP)
            self._canvas.create_rectangle(
                x,
                center_y - bar_h / 2,
                x + _WAVE_BAR_WIDTH,
                center_y + bar_h / 2,
                fill=bar_color,
                outline="",
            )

        self._root.after(_WAVE_UPDATE_MS, self._update_wave)

    def _confirm(self, mode: ConfirmMode) -> None:
        """録音確定処理。"""
        logger.info("Recording confirmed by user. mode=%s", mode)
        self._animation_running = False
        self._stop_hotkey_listener()
        if self._root:
            self._root.destroy()
            self._root = None
        self._on_confirm(mode)

    def _cancel(self) -> None:
        """録音キャンセル処理。"""
        logger.info("Recording cancelled by user.")
        self._animation_running = False
        self._stop_hotkey_listener()
        if self._root:
            self._root.destroy()
            self._root = None
        self._on_cancel()


class TranscribingOverlay:
    """文字起こし中の経過表示ウィンドウ。

    mainloop を使わず update() ループで動作するため、
    メインスレッドで同期的に文字起こしを実行しながら表示を更新できる。
    """

    def __init__(self) -> None:
        self._root: tk.Tk | None = None
        self._status_label: tk.Label | None = None
        self._elapsed_label: tk.Label | None = None
        self._start_time: float = 0.0
        self._dot_count = 0
        self._last_dot_update: float = 0.0

    def show(self) -> None:
        """オーバーレイウィンドウを表示する。"""
        self._root = tk.Tk()
        self._root.title("voice-paste")
        self._root.resizable(False, False)
        self._root.overrideredirect(True)

        win_w, win_h = 300, 120
        x, y = _calc_window_position(
            win_w, win_h,
            config.WINDOW_POSITION,
            config.WINDOW_FOLLOW_CURSOR,
            self._root,
        )
        self._root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self._root.configure(bg=_BG)
        self._root.attributes("-topmost", config.WINDOW_TOPMOST)
        self._root.attributes("-alpha", 0.9)

        if config.WINDOW_HIDDEN:
            self._root.withdraw()

        label_font = tkfont.Font(family="Yu Gothic UI", size=13, weight="bold")
        info_font = tkfont.Font(family="Yu Gothic UI", size=10)
        hint_font = tkfont.Font(family="Yu Gothic UI", size=9)

        self._status_label = tk.Label(
            self._root, text="文字起こし中",
            font=label_font, bg=_BG, fg=_ACCENT,
        )
        self._status_label.pack(pady=(18, 6))

        self._elapsed_label = tk.Label(
            self._root, text="経過: 0.0秒",
            font=info_font, bg=_BG, fg="#888888",
        )
        self._elapsed_label.pack(pady=(0, 8))

        tk.Label(
            self._root,
            text="貼り付けたい場所にカーソルを合わせてください",
            font=hint_font, bg=_BG, fg="#aaaaaa",
        ).pack(pady=(0, 6))

        self._start_time = time.monotonic()
        self._last_dot_update = self._start_time
        self._running = True
        self._root.update()
        self._tick()

    def _tick(self) -> None:
        """0.1秒ごとに経過時間とドットアニメーションを自律更新する。"""
        if not self._running or not self._root:
            return
        self._update_ui()
        self._root.after(100, self._tick)

    def _update_ui(self) -> None:
        """経過時間・ドットアニメーションを更新する。"""
        if not self._root:
            return

        now = time.monotonic()
        elapsed = now - self._start_time

        if self._elapsed_label:
            self._elapsed_label.configure(text=f"経過: {elapsed:.1f}秒")

        # ドットアニメーション
        if now - self._last_dot_update >= 0.5:
            self._dot_count = (self._dot_count + 1) % 4
            dots = "." * self._dot_count
            if self._status_label:
                self._status_label.configure(text=f"文字起こし中{dots}")
            self._last_dot_update = now

        self._root.update()

    def update(self) -> None:
        """UIを更新する。文字起こしループ中に定期的に呼ぶ。"""
        self._update_ui()

    def close(self) -> None:
        """ウィンドウを閉じる。"""
        self._running = False
        if self._root:
            self._root.destroy()
            self._root = None
