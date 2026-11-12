"""UiBridge の知らせを受けて、トレイ・録音の画面・文字起こし中の表示・ダイアログを開く・閉じる・替える。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from voice_paste.features.session.types import Session, SessionState
from voice_paste.shared.errors import DeliveryError, HotkeyError
from voice_paste.shared.settings import (
    GlossaryPresetSettings,
    GlossarySettings,
    Preset,
    Settings,
)
from voice_paste.shared.types import Entry, GlossaryEntry
from voice_paste.ui.tray import RecordingWindowState, Tray, TrayState
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
"""トレイが「録音中」を示す録音セッションの状態。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class UiDeps:
    """画面・トレイが呼ぶ配線済みの関数。ui は features を import せず、main.py がこの束を渡す。"""

    start: Callable[[], None]
    """トレイからの録音の開始（entry=tray を部分適用した start_local_session）。"""

    pause: Callable[[], None]
    """SessionManager.pause。"""

    resume: Callable[[], None]
    """SessionManager.resume。"""

    complete: Callable[[str | None, Preset | None], None]
    """固定の出力先の ID かカスタムプリセットのどちらかで確定する（SessionManager.complete を output_id・preset で呼ぶ）。"""

    cancel: Callable[[], None]
    """SessionManager.cancel。"""

    current_session: Callable[[], Session | None]
    """SessionManager.current。"""

    level: Callable[[], float]
    """録音中の音量（0.0〜1.0。Recorder.level）。"""

    get_settings: Callable[[], Settings]
    """今効いている設定（SettingsStore.get）。"""

    save_settings: Callable[[Settings, Mapping[Path, Sequence[GlossaryEntry]]], bool]
    """設定と、行を変えた用語集の CSV（場所 → 行）を書いて効かせ、再起動が要る項目が変わったかを返す（apply_settings）。"""

    reset_settings: Callable[[], tuple[Settings, bool]]
    """環境の値を空にして読み直した設定を効かせ、その設定と再起動が要る項目が変わったかを返す（reset_applied_settings）。"""

    default_settings: Callable[[], Settings]
    """既定の設定（load_default_settings）。設定画面の入力エラーの数値の例に使う。"""

    settings_dir: Path
    """settings.yaml のあるフォルダ。"""

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

    output_titles: Mapping[str, str]
    """画面に出す出力先の名前（出力先の ID → 名前。API 専用の出力先を除く）。設定画面の欄と録音の画面のボタンが引く。"""

    apply_theme: Callable[[], None]
    """今の設定の ui.theme で画面の明暗を当て直す（apply_theme に QApplication と SettingsStore.get の ui.theme を渡したもの）。"""

    list_glossaries: Callable[[], list[GlossarySettings]]
    """今の設定の用語集の一覧（path は絶対パス。glossaries が空なら今までの用語集の 1 件。resolve_glossaries）。"""

    list_glossary_presets: Callable[[], list[GlossaryPresetSettings]]
    """今の設定の用語集のプリセットの一覧（glossary_presets が空なら「既定」の 1 件。一覧に無い用語集の名前は外す。resolve_glossary_presets）。"""

    read_glossary: Callable[[Path], list[GlossaryEntry]]
    """用語集の CSV の行を、オン・オフと片方が空の行も含めて読む（read_glossary_rows）。読めなければ GlossaryReadError を送出する。"""

    new_glossary_path: Callable[[Collection[Path]], Path]
    """追加する用語集の CSV の場所を、一覧にある場所と重ならないように決める（フォルダを部分適用した next_glossary_path）。"""

    copy: Callable[[str], None]
    """クリップボードへ書く（copy_to_clipboard。書けなければ DeliveryError）。コピーの完了の通知を押したときにもう一度コピーする。"""

    switch_output: Callable[[str], None]
    """文字起こし中に届ける出力先を差し替える（SessionManager.switch_output）。文字起こし中の表示の切り替えのボタンが呼ぶ。"""

    hidden_setting_keys: frozenset[str]
    """設定画面で出さない設定のキー（hidden_setting_keys(unavailable_features(CURRENT_OS))）。Linux では録音中の音量のキーと api.allowed_web_origins。"""

    reports_progress: bool
    """動いているエンジンが区間ごとの進みを知らせるか（local_whisper は True、openai・haas は False）。エンジンの反映は再起動のため、保存した設定ではなく起動で決めた値を持つ。"""


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
        self._recording_hidden = False
        self._indicator_shown = False
        tray.start_requested.connect(deps.start)
        tray.show_window_requested.connect(self.show_recording)
        tray.recopy_requested.connect(self.recopy)
        recording_window.hide_requested.connect(self.hide_recording)
        indicator.output_selected.connect(deps.switch_output)
        tray.settings_requested.connect(self.open_settings)
        tray.restart_requested.connect(lambda: self.request_exit("restart"))
        tray.quit_requested.connect(lambda: self.request_exit("quit"))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def on_notified(self, event: str, detail: str | None) -> None:
        """UiBridge.notified のスロット。知らせの種類ごとに画面とトレイを変える。"""
        if event == "state_changed":
            self._apply_session()
        elif event == "output_changed":
            self._indicator.set_output(detail)  # type: ignore[arg-type]
        elif event == "busy":
            show_busy_dialog(detail)
        elif event == "show_recording_window":
            self.show_recording()
        elif event in FAILURE_EVENTS:
            self._tray.show_failure(event, detail)  # type: ignore[arg-type]
        else:
            logger.warning(f"知らない知らせを受けた（{event}）")

    def on_progressed(self, position_sec: float, duration_sec: float) -> None:
        """UiBridge.progressed のスロット。文字起こし中の表示が出ていれば進みを渡す。"""
        if self._indicator_shown:
            self._indicator.set_progress(position_sec, duration_sec)

    def on_copied(self, text: str) -> None:
        """UiBridge.copied のスロット。トレイにコピーの完了の通知を出す。"""
        self._tray.show_copy_completed(text)

    def recopy(self, text: str) -> None:
        """Tray.recopy_requested のスロット。起こした文字をクリップボードへもう一度書き、書けなければ届けられなかったことを通知する。"""
        try:
            self._deps.copy(text)
        except DeliveryError as error:
            logger.error(f"コピーし直せなかった（{error}）")
            self._tray.show_failure("delivery_failed", str(error))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 Qt の名前
        """QApplication に届く QEvent.Quit を受け、開いている設定画面を確かめずに閉じる。イベントは止めない。"""
        # QApplication.quit は窓へ閉じる要求を送信する前に Quit を渡すため、ここで閉じれば確認で止まらずに抜ける
        if event.type() == QEvent.Type.Quit and self._settings_window is not None:
            self._settings_window.close_without_confirm()
        return False

    def request_exit(self, kind: Literal["restart", "quit"]) -> None:
        """トレイ・設定画面からの再起動・終了。待機中ならすぐ行い、処理中ならアイコンを削除してその回が終わるまで待つ。"""
        session = self._deps.current_session()
        # 待機中か取り消しの猶予中: 猶予中の録音は終了の片付け（SessionManager.close）が捨てるため待たない
        if session is None or session.state == SessionState.CANCEL_PENDING:
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
        """設定画面が保存した後、画面の明暗を当て直し、トレイのホットキーの表示を新しい設定に合わせる（録音の画面は出すたびに設定を読む）。"""
        self._deps.apply_theme()
        self._tray.set_start_hotkey(self._deps.get_settings().hotkeys.start)

    def on_settings_closed(self) -> None:
        """設定画面を手放して破棄し、今の設定でホットキーの受付を始める。"""
        # 欄のシグナルにつないだメソッドが窓を保つため、参照を手放すだけでは消えず、deleteLater で破棄する
        if self._settings_window is not None:
            self._settings_window.deleteLater()
        self._settings_window = None
        try:
            self._deps.resume_hotkeys()
        except HotkeyError as error:
            # 保存の前に受け付けられることを確かめているため、ここに来るのは手で書いた設定のファイルだけ
            logger.error(f"ホットキーを受け付けられなかった（{error}）")

    def hide_recording(self) -> None:
        """RecordingWindow.hide_requested のスロット。その回の録音の画面を隠し、トレイの「録音の画面を表示」を押せるようにする。"""
        # 出ていない（画面を出さない録音・すでに隠している）: 何もしない
        if not self._recording_shown or self._recording_hidden:
            return
        self._recording_window.hide_window()
        self._recording_hidden = True
        self._tray.set_recording_window(RecordingWindowState.HIDDEN)

    def show_recording(self) -> None:
        """隠した録音の画面を、隠す前の位置にフォーカスを取らずに戻す。"""
        # 隠していない（画面を出さない録音・API の録音・すでに出ている）: 何もしない
        if not self._recording_hidden:
            return
        self._recording_hidden = False
        self._recording_window.restore()
        self._tray.set_recording_window(RecordingWindowState.SHOWN)

    # --- 内部 ---

    def _exit(self, kind: Literal["restart", "quit"]) -> None:
        """再起動か終了を行う。"""
        if kind == "restart":
            self._deps.request_restart()
        else:
            self._deps.request_quit()

    def _apply_session(self) -> None:
        """今の録音セッションの入口と状態に合わせて、トレイ・録音の画面・文字起こし中の表示を変える。"""
        session = self._deps.current_session()

        # 録音セッションが無いか取り消しの猶予中: 待機中に戻し、画面を閉じ、待たせた再起動・終了があれば行う
        if session is None or session.state == SessionState.CANCEL_PENDING:
            self._tray.set_state(TrayState.IDLE, busy=False)
            self._close_recording()
            self._close_indicator()
            self._tray.set_recording_window(RecordingWindowState.NOT_RECORDING)
            if self._pending_exit is not None:
                pending, self._pending_exit = self._pending_exit, None
                self._exit(pending)
            return

        # API の録音セッション: トレイだけが状態を示し、画面は出さない
        in_recording = session.state in RECORDING_STATES
        self._tray.set_state(
            TrayState.RECORDING if in_recording else TrayState.TRANSCRIBING, busy=True
        )
        if session.entry == Entry.API:
            # 録音中は画面を出さない録音、文字起こし中は録音していない
            self._tray.set_recording_window(
                RecordingWindowState.NO_WINDOW
                if in_recording
                else RecordingWindowState.NOT_RECORDING
            )
            return

        # ホットキー・トレイの録音セッション: 画面を出さない設定でなければ、状態の画面を出す
        show_windows = not self._deps.get_settings().recording.hide_window
        if in_recording:
            self._close_indicator()
            if show_windows:
                self._show_recording(paused=session.state == SessionState.PAUSED)
            self._tray.set_recording_window(self._recording_window_state(show_windows))
        else:
            # その回に録音の画面を動かしていれば、動かした位置（隠していれば隠す前の位置）を閉じる前に引く
            moved_position = (
                self._recording_window.moved_position() if self._recording_shown else None
            )
            self._close_recording()
            if show_windows and not self._indicator_shown:
                # カスタムプリセットで確定した回は、プリセットのタイトルだけを渡す
                preset = session.output_preset
                self._indicator.open(
                    at=moved_position,
                    output_id=session.output_id,
                    preset_title=None if preset is None else preset.title,
                )
                self._indicator_shown = True
            self._tray.set_recording_window(RecordingWindowState.NOT_RECORDING)

    def _recording_window_state(self, show_windows: bool) -> RecordingWindowState:
        """録音中のトレイの「録音の画面を表示」の状態（画面を出さない設定なら出さない録音、出す設定なら隠しているか出ているか）。"""
        if not show_windows:
            return RecordingWindowState.NO_WINDOW
        return RecordingWindowState.HIDDEN if self._recording_hidden else RecordingWindowState.SHOWN

    def _show_recording(self, *, paused: bool) -> None:
        """録音の画面を表示する（出ていれば一時停止の表示だけ替える。隠していても窓は出さず、状態の表示だけ替える）。"""
        if self._recording_shown:
            self._recording_window.set_paused(paused)
            return
        self._recording_window.open()
        self._recording_shown = True
        self._recording_window.set_paused(paused)

    def _close_recording(self) -> None:
        """録音の画面を閉じる（隠したマーカーも下ろす）。"""
        self._recording_window.close_window()
        self._recording_shown = False
        self._recording_hidden = False

    def _close_indicator(self) -> None:
        """文字起こし中の表示を閉じる。"""
        self._indicator.close_window()
        self._indicator_shown = False
