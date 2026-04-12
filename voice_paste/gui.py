"""録音モーダルウィンドウ（tkinter GUI）モジュール。"""

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
ConfirmMode = Literal["paste_enter", "paste_only"]

# 波形アニメーション設定
_WAVE_UPDATE_MS = 50       # 更新間隔（ms）
_WAVE_BAR_COUNT = 20       # バーの本数
_WAVE_BAR_WIDTH = 6        # バーの幅（px）
_WAVE_BAR_GAP = 3          # バー間隔（px）
_WAVE_MAX_HEIGHT = 160     # バーの最大高さ（px）
_WAVE_MIN_HEIGHT = 3       # バーの最小高さ（px）
_WAVE_COLOR = "#0078d4"    # バーの色


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

    def show(self) -> None:
        """モーダルウィンドウを表示する。"""
        logger.info("Showing recording modal.")
        self._root = tk.Tk()
        self._root.title("voice-paste")
        self._root.resizable(False, False)

        # ウィンドウサイズを計算
        canvas_width = _WAVE_BAR_COUNT * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP) + _WAVE_BAR_GAP
        window_width = max(canvas_width + 40, 360)
        window_height = 260

        # ウィンドウを画面中央に配置
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - window_width) // 2
        y = (screen_h - window_height) // 2
        self._root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self._root.configure(bg="#1e1e1e")
        self._root.attributes("-topmost", True)

        # 波形 Canvas
        self._canvas = tk.Canvas(
            self._root,
            width=canvas_width,
            height=_WAVE_MAX_HEIGHT + 10,
            bg="#1e1e1e",
            highlightthickness=0,
        )
        self._canvas.pack(pady=(14, 8))

        # ボタンフレーム
        btn_frame = tk.Frame(self._root, bg="#1e1e1e")
        btn_frame.pack(pady=(0, 12))

        btn_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")

        # 確定+Enter ボタン（青）
        tk.Button(
            btn_frame, text="確定+Enter", font=btn_font,
            bg="#0078d4", fg="#ffffff",
            activebackground="#005fa3", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=lambda: self._confirm("paste_enter"),
        ).pack(side="left", padx=(0, 6))

        # 確定(貼付のみ) ボタン（緑系）
        tk.Button(
            btn_frame, text="確定", font=btn_font,
            bg="#107c10", fg="#ffffff",
            activebackground="#0b5e0b", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=lambda: self._confirm("paste_only"),
        ).pack(side="left", padx=(0, 6))

        # 中止ボタン
        tk.Button(
            btn_frame, text="中止", font=btn_font,
            bg="#3a3a3a", fg="#cccccc",
            activebackground="#555555", activeforeground="#ffffff",
            relief="flat", padx=12, pady=5, cursor="hand2",
            command=self._cancel,
        ).pack(side="left")

        # キーバインド（ウィンドウフォーカス時）
        self._root.bind("<Return>", lambda _: self._confirm("paste_enter"))
        self._root.bind("<Escape>", lambda _: self._cancel())

        # グローバルホットキーで確定/キャンセル（ウィンドウ非フォーカスでも動作）
        self._hotkey_listener = pynput_keyboard.GlobalHotKeys({
            config.CONFIRM_HOTKEY: lambda: self._hotkey_confirm("paste_enter"),
            config.CONFIRM_PASTE_ONLY_HOTKEY: lambda: self._hotkey_confirm("paste_only"),
            config.CANCEL_HOTKEY: self._hotkey_cancel,
        })
        self._hotkey_listener.start()

        # 波形アニメーション開始
        self._animation_running = True
        self._update_wave()

        self._root.mainloop()

    def _hotkey_confirm(self, mode: ConfirmMode) -> None:
        """グローバルホットキーからの確定（メインスレッドへ委譲）。"""
        if self._root:
            self._root.after(0, lambda: self._confirm(mode))

    def _hotkey_cancel(self) -> None:
        """グローバルホットキーからのキャンセル（メインスレッドへ委譲）。"""
        if self._root:
            self._root.after(0, self._cancel)

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_listener:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

    def _update_wave(self) -> None:
        """波形アニメーションを更新する。"""
        if not self._animation_running or self._canvas is None or self._root is None:
            return

        if self._recorder is not None:
            level = self._recorder.get_level()
        else:
            level = 0.0

        canvas_w = self._canvas.winfo_width() or (_WAVE_BAR_COUNT * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP))
        canvas_h = self._canvas.winfo_height() or (_WAVE_MAX_HEIGHT + 10)
        center_y = canvas_h // 2

        import random
        self._canvas.delete("all")

        for i in range(_WAVE_BAR_COUNT):
            center_factor = 1.0 - abs(i - _WAVE_BAR_COUNT / 2) / (_WAVE_BAR_COUNT / 2) * 0.4
            noise = random.uniform(0.5, 1.5) if level > 0.01 else random.uniform(0.8, 1.2)
            target_h = max(
                _WAVE_MIN_HEIGHT,
                min(_WAVE_MAX_HEIGHT, level * _WAVE_MAX_HEIGHT * center_factor * noise * 8),
            )
            self._bar_heights[i] = self._bar_heights[i] * 0.6 + target_h * 0.4

            bar_h = self._bar_heights[i]
            x = _WAVE_BAR_GAP + i * (_WAVE_BAR_WIDTH + _WAVE_BAR_GAP)
            self._canvas.create_rectangle(
                x,
                center_y - bar_h / 2,
                x + _WAVE_BAR_WIDTH,
                center_y + bar_h / 2,
                fill=_WAVE_COLOR,
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
