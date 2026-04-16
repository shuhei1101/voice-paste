"""エントリーポイント。起動フローを制御する高レベルモジュール。"""

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from pynput import keyboard as pynput_keyboard

from voice_paste import config
from voice_paste.logger import setup_logger, get_logger
from voice_paste.audio.recorder import AudioRecorder
from voice_paste.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste.input.keyboard_sender import copy_to_clipboard, send_paste, send_enter
from voice_paste.gui import RecordingModal, TranscribingOverlay, ConfirmMode
from voice_paste.utils import (
    load_prompt,
    load_yogo,
    build_initial_prompt,
    apply_yogo_replacements,
)
from voice_paste.history import save_history, cleanup_history
from voice_paste.constants import DEFAULT_AUDIO_TMP

logger = get_logger(__name__)

# ディスパッチキューに流すコマンド種別
DispatchCommand = Literal["session", "quit", "settings", "restart"]


def _run_once(
    recorder: AudioRecorder,
    transcriber: WhisperTranscriber,
    tray_icon: object | None = None,
) -> None:
    """1 回分の録音→文字起こし→貼り付けフロー。"""
    result: ConfirmMode | None = None

    def on_confirm(mode: ConfirmMode) -> None:
        nonlocal result
        result = mode

    def on_cancel() -> None:
        logger.info("Cancelled by user.")

    # トレイアイコンを赤(録音中)に
    if tray_icon:
        from voice_paste.tray import update_tray_state
        update_tray_state(tray_icon, "recording")

    recorder.start()
    modal = RecordingModal(on_confirm=on_confirm, on_cancel=on_cancel, recorder=recorder)
    modal.show()

    if result is None:
        recorder.cancel()
        if tray_icon:
            from voice_paste.tray import update_tray_state
            update_tray_state(tray_icon, "idle")
        logger.info("Session exited without output.")
        return

    audio_file: Path = recorder.stop_and_save(DEFAULT_AUDIO_TMP)

    # プロンプト・用語集を毎回読み込み（編集が即反映される）
    raw_prompt = load_prompt(config.PROMPT_FILE)
    yogo = load_yogo(config.YOGO_FILE)
    prompt = build_initial_prompt(raw_prompt, yogo)

    # トレイアイコンを緑(文字起こし中)に
    if tray_icon:
        from voice_paste.tray import update_tray_state
        update_tray_state(tray_icon, "transcribing")

    # 文字起こし中オーバーレイ表示
    overlay = TranscribingOverlay()
    overlay.show()

    text = transcriber.transcribe(
        audio_file, prompt=prompt,
        on_segment=overlay.update,
    )
    logger.info("Transcribed text: %s", text)

    text = apply_yogo_replacements(text, yogo)

    overlay.close()

    # トレイアイコンをアイドルに戻す
    if tray_icon:
        from voice_paste.tray import update_tray_state
        update_tray_state(tray_icon, "idle")

    if not text:
        logger.warning("Transcription result is empty.")
        return

    # 履歴保存
    save_history(audio_file, text)

    copy_to_clipboard(text)

    if result in ("paste_enter", "paste_only"):
        send_paste()

    if result == "paste_enter":
        send_enter(delay=config.PASTE_ENTER_DELAY)

    logger.info("Session completed successfully. mode=%s", result)


def _run_one_shot() -> None:
    """1 回実行して終了するモード。"""
    recorder = AudioRecorder()
    transcriber = WhisperTranscriber()
    _run_once(recorder, transcriber)


def _restart_process() -> None:
    """現在のプロセスを新しいプロセスで再起動する。"""
    logger.info("Restarting process: %s %s", sys.executable, sys.argv)
    # 現在の環境変数をそのまま引き継いで新プロセスを起動
    subprocess.Popen(
        [sys.executable] + sys.argv,
        env=os.environ.copy(),
    )
    os._exit(0)


def _run_resident() -> None:
    """
    常駐モード。トレイアイコン + グローバルホットキーで録音を起動する。
    """
    logger.info("Resident mode. Loading model...")
    recorder = AudioRecorder()
    transcriber = WhisperTranscriber()
    logger.info("Model loaded. Waiting for hotkey: %s", config.RESIDENT_HOTKEY)
    print(f"[voice-paste] resident mode ready. hotkey={config.RESIDENT_HOTKEY}")

    # ディスパッチキュー: セッション起動要求 / 終了要求を受け付ける
    dispatch_queue: "queue.Queue[DispatchCommand]" = queue.Queue()
    # 同時セッション抑止フラグ
    session_active = threading.Event()

    def request_session() -> None:
        if session_active.is_set():
            logger.warning("Session already running. Trigger ignored.")
            return
        dispatch_queue.put("session")

    def request_quit() -> None:
        dispatch_queue.put("quit")

    def request_restart() -> None:
        dispatch_queue.put("restart")

    def request_settings() -> None:
        if session_active.is_set():
            logger.warning("Session active. Settings ignored.")
            return
        dispatch_queue.put("settings")

    # トレイアイコン構築（遅延 import で one-shot モードへの影響を防ぐ）
    from voice_paste.tray import build_tray_icon

    tray_icon = build_tray_icon(
        hotkey=config.RESIDENT_HOTKEY,
        on_start_session=request_session,
        on_settings=request_settings,
        on_restart=request_restart,
        on_quit=request_quit,
    )

    # pynput のグローバルホットキーリスナー
    hotkey_listener = pynput_keyboard.GlobalHotKeys(
        {config.RESIDENT_HOTKEY: request_session}
    )

    tray_icon.run_detached()
    hotkey_listener.start()

    # 履歴クリーンアップの間隔（秒）
    _CLEANUP_INTERVAL = 3600
    _last_cleanup = time.monotonic()

    try:
        while True:
            try:
                cmd = dispatch_queue.get(timeout=0.5)
            except queue.Empty:
                # 定期クリーンアップ
                now = time.monotonic()
                if now - _last_cleanup >= _CLEANUP_INTERVAL:
                    cleanup_history()
                    _last_cleanup = now
                continue

            if cmd == "quit":
                logger.info("Dispatch loop received quit.")
                break

            if cmd == "restart":
                logger.info("Dispatch loop received restart.")
                _restart_process()
                break  # フォールバック（_restart_processが戻ってきた場合）

            if cmd == "settings":
                session_active.set()
                try:
                    from voice_paste.settings_gui import SettingsWindow

                    def _on_settings_saved(changed: dict[str, str]) -> None:
                        nonlocal hotkey_listener
                        if "RESIDENT_HOTKEY" in changed:
                            hotkey_listener.stop()
                            hotkey_listener = pynput_keyboard.GlobalHotKeys(
                                {config.RESIDENT_HOTKEY: request_session}
                            )
                            hotkey_listener.start()
                            tray_icon.title = "voice-paste: 待機中"
                            logger.info("Hotkey re-registered: %s", config.RESIDENT_HOTKEY)

                    settings_win = SettingsWindow(
                        on_save=_on_settings_saved,
                        on_restart=_restart_process,
                    )
                    settings_win.show()
                except Exception:
                    logger.exception("Settings window failed.")
                finally:
                    session_active.clear()
                continue

            if cmd == "session":
                session_active.set()
                try:
                    _run_once(recorder, transcriber, tray_icon=tray_icon)
                except Exception:
                    logger.exception("Session failed.")
                finally:
                    session_active.clear()
    except KeyboardInterrupt:
        logger.info("Resident mode interrupted by user.")
    finally:
        try:
            hotkey_listener.stop()
        except Exception:
            logger.exception("Failed to stop hotkey listener.")
        try:
            tray_icon.stop()
        except Exception:
            pass


def run() -> None:
    """メイン処理フローを実行する。"""
    setup_logger(config.LOG_LEVEL)
    logger.info("voice-paste started. resident=%s", config.RESIDENT_MODE)
    logger.info("config.WAVE_GAIN=%s", config.WAVE_GAIN)

    # 起動時に古い履歴を削除
    cleanup_history()

    if config.RESIDENT_MODE:
        _run_resident()
    else:
        _run_one_shot()

    logger.info("voice-paste exited.")
