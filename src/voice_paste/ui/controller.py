"""UiBridge の知らせを受けて、トレイ・録音の画面・文字起こし中の表示・ダイアログを開く・閉じる・替える。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject

from voice_paste.features.session.types import Session, SessionState
from voice_paste.shared.errors import HotkeyError
from voice_paste.shared.settings import Settings
from voice_paste.shared.types import Entry
from voice_paste.ui.tray import Tray, TrayState
from voice_paste.ui.windows.busy_dialog import show_busy_dialog
from voice_paste.ui.windows.recording_window import RecordingWindow
from voice_paste.ui.windows.settings_window import SettingsWindow
from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

logger = logging.getLogger(__name__)

FAILURE_EVENTS: frozenset[str] = frozenset(
    {"microphone_unavailable", "transcription_failed", "delivery_failed", "api_unavailable"}
)
"""トレイの通知で知らせる失敗の種類。"""

RECORDING_STATES: frozenset[SessionState] = frozenset(
    {SessionState.RECORDING, SessionState.PAUSED, SessionState.STOPPED}
)
"""トレイが「録音中」を示すセッションの状態。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class UiDeps:
    """画面・トレイが呼ぶ配線済みの関数。ui は features を import せず、main.py がこの束を渡す。"""

    start: Callable[[], None]
    """トレイからの録音の開始（entry=tray を部分適用した start_local_session）。"""

    pause: Callable[[], None]
    """SessionManager.pause。"""

    resume: Callable[[], None]
    """SessionManager.resume。"""

    complete: Callable[[str, str | None], None]
    """出力先の ID と出力先に固有の宛先で確定する（SessionManager.complete を output_id・output_target で呼ぶ）。"""

    cancel: Callable[[], None]
    """SessionManager.cancel。"""

    current_session: Callable[[], Session | None]
    """SessionManager.current。"""

    level: Callable[[], float]
    """録音中の音量（0.0〜1.0。Recorder.level）。"""

    get_settings: Callable[[], Settings]
    """今効いている設定（SettingsStore.get）。"""

    save_settings: Callable[[Settings], bool]
    """設定を書いて効かせ、再起動が要る項目が変わったかを返す（apply_settings）。"""

    settings_dir: Path
    """settings.toml のあるフォルダ。"""

    log_dir: Path
    """ログのフォルダ。"""

    request_restart: Callable[[], None]
    """終わった後に起動し直すようにしてイベントループを抜ける。"""

    request_quit: Callable[[], None]
    """イベントループを抜ける（QApplication.quit）。"""

    suspend_hotkeys: Callable[[], None]
    """ホットキーの受付を止める（設定画面を開いている間、欄で押したキーで録音が始まらないようにする）。"""

    resume_hotkeys: Callable[[], None]
    """今の設定でホットキーの受付を始める（設定画面を閉じたときに呼ぶ）。"""


class UiController(QObject):
    """UiBridge の知らせを受けて、トレイ・録音の画面・文字起こし中の表示・ダイアログを開く・閉じる・替える。

    処理中に選ばれた再起動・終了を待たせる。全てのメソッドはメインスレッドで呼ぶ。
    """

    def __init__(
        self,
        deps: UiDeps,
        *,
        tray: Tray,
        recording_window: RecordingWindow,
        indicator: TranscribingIndicator,
    ) -> None:
        """配線済みの関数と、トレイ・録音の画面・文字起こし中の表示を受け、トレイの操作をつなぐ。"""
        super().__init__()
        self._deps = deps
        self._tray = tray
        self._recording_window = recording_window
        self._indicator = indicator
        self._settings_window: SettingsWindow | None = None
        self._pending_exit: Literal["restart", "quit"] | None = None
        self._recording_shown = False
        self._indicator_shown = False
        tray.start_requested.connect(deps.start)
        tray.settings_requested.connect(self.open_settings)
        tray.restart_requested.connect(lambda: self.request_exit("restart"))
        tray.quit_requested.connect(lambda: self.request_exit("quit"))

    def on_notified(self, event: str, detail: str | None) -> None:
        """UiBridge.notified のスロット。知らせの種類ごとに画面とトレイを変える。"""
        if event == "state_changed":
            self._apply_session()
        elif event == "busy":
            show_busy_dialog()
        elif event in FAILURE_EVENTS:
            self._tray.show_failure(event, detail)  # type: ignore[arg-type]
        else:
            logger.warning(f"知らない知らせを受けた（{event}）")

    def on_progressed(self, position_sec: float, duration_sec: float) -> None:
        """UiBridge.progressed のスロット。文字起こし中の表示が出ていれば進みを渡す。"""
        if self._indicator_shown:
            self._indicator.set_progress(position_sec, duration_sec)

    def request_exit(self, kind: Literal["restart", "quit"]) -> None:
        """トレイ・設定画面からの再起動・終了。待機中ならすぐ行い、処理中ならアイコンを消してその回が終わるまで待つ。"""
        session = self._deps.current_session()
        if session is None:
            self._exit(kind)
            return
        self._pending_exit = kind
        self._tray.hide()
        logger.info(f"処理中のため再起動・終了を待たせた（{kind}・{session.id}）")

    def open_settings(self) -> None:
        """設定画面を開く。開いていれば前面に出すだけにする。新しく開くときはホットキーの受付を止める。"""
        if self._settings_window is not None:
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        self._deps.suspend_hotkeys()
        window = SettingsWindow(self._deps)
        window.saved.connect(self.on_settings_saved)
        window.restart_requested.connect(lambda: self.request_exit("restart"))
        window.closed.connect(self.on_settings_closed)
        self._settings_window = window
        window.show()
        window.raise_()
        window.activateWindow()

    def on_settings_saved(self) -> None:
        """設定画面が保存した後、トレイのホットキーの表示を新しい設定に合わせる（録音の画面は出すたびに設定を読む）。"""
        self._tray.set_start_hotkey(self._deps.get_settings().hotkeys.start)

    def on_settings_closed(self) -> None:
        """設定画面を手放し、今の設定でホットキーの受付を始める。"""
        self._settings_window = None
        try:
            self._deps.resume_hotkeys()
        except HotkeyError as error:
            # 保存の前に受け付けられることを確かめているため、ここに来るのは手で書いた settings.toml だけ
            logger.error(f"ホットキーを受け付けられなかった（{error}）")

    # --- 内部 ---

    def _exit(self, kind: Literal["restart", "quit"]) -> None:
        """再起動か終了を行う。"""
        if kind == "restart":
            self._deps.request_restart()
        else:
            self._deps.request_quit()

    def _apply_session(self) -> None:
        """今のセッションの入口と状態に合わせて、トレイ・録音の画面・文字起こし中の表示を変える。"""
        session = self._deps.current_session()

        # セッションが無い: 待機中に戻し、画面を閉じ、待たせた再起動・終了があれば行う
        if session is None:
            self._tray.set_state(TrayState.IDLE, busy=False)
            self._close_recording()
            self._close_indicator()
            if self._pending_exit is not None:
                pending, self._pending_exit = self._pending_exit, None
                self._exit(pending)
            return

        # API のセッション: トレイだけが状態を示し、画面は出さない
        in_recording = session.state in RECORDING_STATES
        self._tray.set_state(
            TrayState.RECORDING if in_recording else TrayState.TRANSCRIBING, busy=True
        )
        if session.entry == Entry.API:
            return

        # ホットキー・トレイのセッション: 画面を出さない設定でなければ、状態の画面を出す
        show_windows = not self._deps.get_settings().recording.hide_window
        if in_recording:
            self._close_indicator()
            if show_windows:
                self._show_recording(paused=session.state == SessionState.PAUSED)
        else:
            self._close_recording()
            if show_windows and not self._indicator_shown:
                self._indicator.open()
                self._indicator_shown = True

    def _show_recording(self, *, paused: bool) -> None:
        """録音の画面を出す（出ていれば一時停止の表示だけ替える）。"""
        if self._recording_shown:
            self._recording_window.set_paused(paused)
            return
        self._recording_window.open()
        self._recording_shown = True
        self._recording_window.set_paused(paused)

    def _close_recording(self) -> None:
        """録音の画面を閉じる。"""
        self._recording_window.close_window()
        self._recording_shown = False

    def _close_indicator(self) -> None:
        """文字起こし中の表示を閉じる。"""
        self._indicator.close_window()
        self._indicator_shown = False
