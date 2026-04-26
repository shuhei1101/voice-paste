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
from voice_paste.transcription.transcribable import Transcribable
from voice_paste.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste.input.keyboard_sender import copy_to_clipboard, send_paste, send_enter
from voice_paste.gui import RecordingModal, TranscribingOverlay, ConfirmMode
from voice_paste.utils import (
    load_yogo,
    apply_yogo_replacements,
)
from voice_paste.history import save_history, cleanup_history
from voice_paste.constants import DEFAULT_AUDIO_TMP, PID_FILE

logger = get_logger(__name__)

# ディスパッチキューに流すコマンド種別
DispatchCommand = Literal["session", "quit", "settings", "restart"]


def _ensure_single_instance() -> None:
    """起動時に既存プロセスをキルして単一インスタンスを保証する。"""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(old_pid)],
                    capture_output=True,
                )
                if result.returncode == 0:
                    logger.info("Killed existing instance (PID=%d).", old_pid)
                    time.sleep(0.5)
        except (ValueError, OSError):
            pass

    PID_FILE.write_text(str(os.getpid()))

    import atexit
    atexit.register(_cleanup_pid_file)


def _cleanup_pid_file() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


def _find_edge() -> str | None:
    """Edge 実行ファイルのパスを返す。見つからなければ None。"""
    import shutil
    from pathlib import Path as _Path
    if shutil.which("msedge"):
        return "msedge"
    for candidate in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if _Path(candidate).exists():
            return candidate
    return None


def _open_ai_app(url: str, name: str) -> None:
    """AI アプリを PWA モードで起動する。Edge が見つからない場合は通常起動。"""
    edge = _find_edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}"])
        logger.info("Opened AI app via Edge PWA: %s (%s)", name, url)
    else:
        subprocess.Popen(["cmd", "/c", "start", "", url])
        logger.info("Opened AI app via default browser: %s (%s)", name, url)


def _create_transcriber() -> Transcribable:
    """設定に応じた文字起こしエンジンを生成する。"""
    if config.TRANSCRIPTION_ENGINE == "openai":
        from voice_paste.transcription.openai_transcriber import OpenAITranscriber
        return OpenAITranscriber()
    return WhisperTranscriber()


def _run_once(
    recorder: AudioRecorder,
    transcriber: Transcribable,
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

    # 用語集を毎回読み込み（編集が即反映される）
    yogo = load_yogo(config.YOGO_FILE)

    # トレイアイコンを緑(文字起こし中)に
    if tray_icon:
        from voice_paste.tray import update_tray_state
        update_tray_state(tray_icon, "transcribing")

    # 文字起こし中オーバーレイ表示
    overlay = TranscribingOverlay()
    overlay.show()

    # WAV の総再生時間をオーバーレイに事前セット（最初から全体秒数を表示するため）
    try:
        from scipy.io import wavfile as _wavfile
        _sr, _data = _wavfile.read(str(audio_file))
        overlay.set_total(len(_data) / _sr)
    except Exception:
        pass

    # transcribe をバックグラウンドスレッドで実行し、メインスレッドで UI を更新する
    _result: dict = {"text": None, "error": None}

    def _transcribe_bg() -> None:
        try:
            _result["text"] = transcriber.transcribe(
                audio_file,
                on_segment=overlay.update,
            )
        except Exception as exc:
            _result["error"] = exc

    t = threading.Thread(target=_transcribe_bg, daemon=True)
    t.start()
    while t.is_alive():
        overlay.tick()
        t.join(timeout=0.05)

    if _result["error"]:
        overlay.close()
        if tray_icon:
            from voice_paste.tray import update_tray_state
            update_tray_state(tray_icon, "idle")
        logger.exception("Transcription failed.", exc_info=_result["error"])
        import tkinter.messagebox as mb
        mb.showerror("文字起こしエラー", f"文字起こしに失敗しました:\n{_result['error']}")
        return

    text: str = _result["text"] or ""
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

    if result.startswith("send_to_ai_"):
        try:
            idx = int(result.removeprefix("send_to_ai_"))
            app = config.AI_SEND_APPS[idx]
        except (ValueError, IndexError):
            logger.warning("Invalid send_to_ai mode: %s", result)
        else:
            _open_ai_app(app["url"], app["name"])
            time.sleep(config.AI_SEND_DELAY)
            send_paste()
            send_enter(delay=config.PASTE_ENTER_DELAY)

    logger.info("Session completed successfully. mode=%s", result)


def _run_one_shot() -> None:
    """1 回実行して終了するモード。"""
    recorder = AudioRecorder()
    transcriber = _create_transcriber()
    _run_once(recorder, transcriber)


def _restart_process() -> None:
    """現在のプロセスを新しいプロセスで再起動する。"""
    env = os.environ.copy()
    # sys.argv[0] からプロジェクトルートを特定し PYTHONPATH に先頭追加する。
    # これにより venv の editable install より worktree 側のコードが優先され、
    # worktree で実行中に設定保存で再起動しても同じコードが継続使用される。
    if sys.argv:
        script = Path(sys.argv[0])
        if script.exists():
            project_root = str(script.parent.parent.resolve())
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (project_root + os.pathsep + existing).rstrip(os.pathsep)
    logger.info("Restarting process: %s %s (PYTHONPATH=%s)", sys.executable, sys.argv, env.get("PYTHONPATH", ""))
    subprocess.Popen([sys.executable] + sys.argv, env=env)
    os._exit(0)


def _run_resident() -> None:
    """
    常駐モード。トレイアイコン + グローバルホットキーで録音を起動する。
    """
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

    # トレイアイコンをモデル読み込み前に表示（起動中であることをユーザーに示す）
    from voice_paste.tray import build_tray_icon, update_tray_state

    tray_icon = build_tray_icon(
        hotkey=config.RESIDENT_HOTKEY,
        on_start_session=request_session,
        on_settings=request_settings,
        on_restart=request_restart,
        on_quit=request_quit,
    )
    tray_icon.run_detached()
    update_tray_state(tray_icon, "loading")

    # モデル読み込み（トレイ表示後に実行するため起動フィードバックが得られる）
    logger.info("Resident mode. Loading transcriber (engine=%s)...", config.TRANSCRIPTION_ENGINE)
    recorder = AudioRecorder()
    transcriber = _create_transcriber()
    logger.info("Transcriber loaded. Waiting for hotkey: %s", config.RESIDENT_HOTKEY)
    print(f"[voice-paste] resident mode ready. hotkey={config.RESIDENT_HOTKEY}")

    update_tray_state(tray_icon, "idle")

    # pynput のグローバルホットキーリスナー
    hotkey_listener = pynput_keyboard.GlobalHotKeys(
        {config.RESIDENT_HOTKEY: request_session}
    )
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

    _ensure_single_instance()

    # 起動時に古い履歴を削除
    cleanup_history()

    if config.RESIDENT_MODE:
        _run_resident()
    else:
        _run_one_shot()

    logger.info("voice-paste exited.")
