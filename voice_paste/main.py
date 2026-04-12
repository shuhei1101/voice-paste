"""エントリーポイント。起動フローを制御する高レベルモジュール。"""

import queue
import threading
from pathlib import Path
from typing import Literal

from pynput import keyboard as pynput_keyboard

from voice_paste import config
from voice_paste.logger import setup_logger, get_logger
from voice_paste.audio.recorder import AudioRecorder
from voice_paste.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste.input.keyboard_sender import copy_to_clipboard, send_paste, send_enter
from voice_paste.gui import RecordingModal, ConfirmMode
from voice_paste.utils import load_prompt
from voice_paste.constants import DEFAULT_AUDIO_TMP

logger = get_logger(__name__)

# ディスパッチキューに流すコマンド種別
DispatchCommand = Literal["session", "quit", "settings"]


def _run_once(recorder: AudioRecorder, transcriber: WhisperTranscriber, prompt: str) -> None:
    """1 回分の録音→文字起こし→貼り付けフロー。"""
    result: ConfirmMode | None = None

    def on_confirm(mode: ConfirmMode) -> None:
        nonlocal result
        result = mode

    def on_cancel() -> None:
        logger.info("Cancelled by user.")

    recorder.start()
    modal = RecordingModal(on_confirm=on_confirm, on_cancel=on_cancel, recorder=recorder)
    modal.show()

    if result is None:
        recorder.cancel()
        logger.info("Session exited without output.")
        return

    audio_file: Path = recorder.stop_and_save(DEFAULT_AUDIO_TMP)

    text = transcriber.transcribe(audio_file, prompt=prompt)
    logger.info("Transcribed text: %s", text)

    if not text:
        logger.warning("Transcription result is empty.")
        return

    copy_to_clipboard(text)
    send_paste()

    if result == "paste_enter":
        send_enter()

    logger.info("Session completed successfully. mode=%s", result)


def _run_one_shot() -> None:
    """1 回実行して終了するモード。"""
    recorder = AudioRecorder()
    transcriber = WhisperTranscriber()
    prompt = load_prompt(config.PROMPT_FILE)
    _run_once(recorder, transcriber, prompt)


def _run_resident() -> None:
    """
    常駐モード。トレイアイコン + グローバルホットキーで録音を起動する。

    アーキテクチャ:
      - メインスレッド: ディスパッチループを回し、キューから受け取ったセッション要求に
        応じて ``_run_once`` を実行する。Tk のモーダルはメインスレッドで動かす必要があるため。
      - pystray: ``run_detached()`` でバックグラウンドスレッドに配置する。
      - pynput GlobalHotKeys: 別スレッドでリスナー起動。
      - トリガー経路（ホットキー / トレイメニュー）は全て同じキューへ要求を enqueue する。
    """
    logger.info("Resident mode. Loading model...")
    recorder = AudioRecorder()
    transcriber = WhisperTranscriber()
    prompt = load_prompt(config.PROMPT_FILE)
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
        on_quit=request_quit,
    )

    # pynput のグローバルホットキーリスナー
    hotkey_listener = pynput_keyboard.GlobalHotKeys(
        {config.RESIDENT_HOTKEY: request_session}
    )

    tray_icon.run_detached()
    hotkey_listener.start()

    try:
        while True:
            try:
                cmd = dispatch_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if cmd == "quit":
                logger.info("Dispatch loop received quit.")
                break

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
                            tray_icon.title = f"voice-paste (hotkey: {config.RESIDENT_HOTKEY})"
                            logger.info("Hotkey re-registered: %s", config.RESIDENT_HOTKEY)

                    settings_win = SettingsWindow(on_save=_on_settings_saved)
                    settings_win.show()
                except Exception:
                    logger.exception("Settings window failed.")
                finally:
                    session_active.clear()
                continue

            if cmd == "session":
                session_active.set()
                try:
                    _run_once(recorder, transcriber, prompt)
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

    if config.RESIDENT_MODE:
        _run_resident()
    else:
        _run_one_shot()

    logger.info("voice-paste exited.")
