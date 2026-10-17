"""システムトレイのアイコン・メニュー・通知。"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from voice_paste.ui.windows.settings_window import format_hotkey

logger = logging.getLogger(__name__)

TRAY_ICON_DIR: Path = Path(__file__).resolve().parents[3] / "resources" / "tray"
"""トレイのアイコンの画像（`{TrayState の値}.png`）を置いたフォルダ。"""

TOOLTIP_PREFIX: str = "voice-paste: "
"""アイコンのヒントの先頭。"""

MESSAGE_MSEC: int = 10_000
"""通知を出しておく時間（ミリ秒）。通知は数秒で畳まれ、通知センターには残らない。"""

type FailureEvent = Literal[
    "microphone_unavailable",
    "transcription_failed",
    "delivery_failed",
    "api_unavailable",
    "engine_unavailable",
    "settings_invalid",
]
"""トレイの通知で知らせる失敗の種類（engine_unavailable・settings_invalid は起動の失敗）。"""

FAILURE_TITLES: dict[str, str] = {
    "microphone_unavailable": "録音を始められませんでした",
    "transcription_failed": "文字起こしに失敗しました",
    "delivery_failed": "届けられませんでした",
    "api_unavailable": "API を使えません",
    "engine_unavailable": "起動に失敗しました",
    "settings_invalid": "起動に失敗しました",
}
"""知らせの種類ごとの、通知の見出し。"""

MICROPHONE_BODY: str = (
    "マイクを開けません。マイクがつながっているか、ほかのアプリが使っていないかを確かめてください。"
)
"""マイクを開けないときの通知の本文（理由は固定）。"""

FAILURE_BODY_SUFFIXES: dict[str, str] = {
    "transcription_failed": "録音は履歴に残っています。",
    "delivery_failed": "起こした文字は履歴に残っています。",
    "api_unavailable": "ホットキーとトレイからの録音は使えます。",
}
"""知らせの種類ごとの、理由の後に添える文（履歴に残っていること・次にすること）。"""

COPY_COMPLETED_TITLE: str = "コピーしました"
"""コピーの完了の通知の見出し。"""

COPY_COMPLETED_BODY: str = "任意の場所に貼り付けてください。この通知を押すと、もう一度コピーします。"
"""コピーの完了の通知の本文（固定の文）。"""

STARTUP_BODY_FORMATS: dict[str, str] = {
    "engine_unavailable": "文字起こしのエンジンを準備できません（{reason}）。設定を直して再起動してください。",
    "settings_invalid": "設定ファイルを読めません（{reason}）。設定フォルダの settings.toml を直して再起動してください。",
}
"""起動に失敗したときの通知の本文（知らせの種類ごと）。"""


class TrayState(StrEnum):
    """トレイのアイコンとヒントの出し分け。値は `resources/tray/{値}.png` のファイル名。"""

    STARTING = "starting"
    """準備中（起動してから待機中になるまで）。"""

    IDLE = "idle"
    """待機中（セッションが無い）。"""

    RECORDING = "recording"
    """録音中（recording・paused・stopped）。"""

    TRANSCRIBING = "transcribing"
    """文字起こし中（transcribing・delivering）。"""

    FAILED = "failed"
    """失敗（文字起こしのエンジンを準備できなかった起動。次の起動まで続く）。"""


STATE_NAMES: dict[TrayState, str] = {
    TrayState.STARTING: "準備中",
    TrayState.IDLE: "待機中",
    TrayState.RECORDING: "録音中",
    TrayState.TRANSCRIBING: "文字起こし中",
    TrayState.FAILED: "失敗",
}
"""状態ごとの、ヒントに出す名前。"""


class RecordingWindowState(StrEnum):
    """トレイの「録音の画面を出す」の出し分け。"""

    HIDDEN = "hidden"
    """隠している（ホットキー・トレイの recording・paused で、その回の録音の画面を隠している。項目を押せる）。"""

    SHOWN = "shown"
    """表示中（ホットキー・トレイの recording・paused で、録音の画面が出ている）。"""

    NO_WINDOW = "no_window"
    """画面を出さない録音（`recording.hide_window` がオンの録音か、API の録音）。"""

    NOT_RECORDING = "not_recording"
    """録音していない（待機中・文字起こし中・準備に失敗した起動）。"""


START_TEXT: str = "録音を始める"
SHOW_WINDOW_TEXT: str = "録音の画面を出す"
SETTINGS_TEXT: str = "設定…"
BUSY_SUFFIX: str = "（処理中）"
FAILED_SUFFIX: str = "（準備に失敗）"
"""メニューの「録音を始める」「録音の画面を出す」「設定…」の文言と、押せない理由の添え字。"""

SHOW_WINDOW_REASONS: dict[RecordingWindowState, str] = {
    RecordingWindowState.SHOWN: "（表示中）",
    RecordingWindowState.NO_WINDOW: "（画面を出さない録音）",
    RecordingWindowState.NOT_RECORDING: "（録音していません）",
}
"""「録音の画面を出す」を押せないときに、項目名へ添える理由（隠している間は押せるため添えない）。"""


class Tray(QObject):
    """QSystemTrayIcon で状態ごとのアイコン・メニュー・通知を出す。選ばれた操作は Signal で伝える。"""

    start_requested = Signal()
    """「録音を始める」・アイコンの左クリック。"""

    settings_requested = Signal()
    """「設定…」。"""

    restart_requested = Signal()
    """「再起動」。"""

    quit_requested = Signal()
    """「終了」。"""

    show_window_requested = Signal()
    """「録音の画面を出す」・録音の画面を隠している間のアイコンの左クリック。"""

    recopy_requested = Signal(str)
    """コピーの完了の通知を押した（その通知のときに起こした文字を渡す）。"""

    def __init__(self, settings_dir: Path, log_dir: Path) -> None:
        """設定とログのフォルダを受け、準備中のアイコンとメニューを出す。"""
        super().__init__()
        self._settings_dir = settings_dir
        self._log_dir = log_dir
        self._failed = False
        self._copied_text: str | None = None
        self._start_hotkey = ""
        self._start_label = START_TEXT
        self._window_state = RecordingWindowState.NOT_RECORDING
        self._icons = {state: QIcon(str(TRAY_ICON_DIR / f"{state.value}.png")) for state in TrayState}

        self._icon = QSystemTrayIcon(self)
        menu = QMenu()
        self._menu = menu
        self._start_action = self._add_item(menu, "menu_start", START_TEXT)
        self._show_window_action = self._add_item(menu, "menu_show_window", SHOW_WINDOW_TEXT)
        menu.addSeparator()
        self._settings_action = self._add_item(menu, "menu_settings", SETTINGS_TEXT)
        open_settings_folder = self._add_item(
            menu, "menu_open_settings_folder", "設定フォルダを開く"
        )
        open_log_folder = self._add_item(menu, "menu_open_log_folder", "ログフォルダを開く")
        menu.addSeparator()
        restart_action = self._add_item(menu, "menu_restart", "再起動")
        quit_action = self._add_item(menu, "menu_quit", "終了")

        self._start_action.triggered.connect(self.start_requested)
        self._show_window_action.triggered.connect(self.show_window_requested)
        self._settings_action.triggered.connect(self.settings_requested)
        open_settings_folder.triggered.connect(lambda: self._open_folder(self._settings_dir))
        open_log_folder.triggered.connect(self._open_log_folder)
        restart_action.triggered.connect(self.restart_requested)
        quit_action.triggered.connect(self.quit_requested)

        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.messageClicked.connect(self._on_message_clicked)
        # Windows はボタンの名前を、アイコンを出した時点のヒントと今のヒントをつないで作る。
        # 準備中のヒントが残らないよう、画像だけを付けてアイコンを出してから、ヒントを付ける
        self._icon.setIcon(self._icons[TrayState.STARTING])
        self._icon.show()
        self.set_state(TrayState.STARTING, busy=False)
        self.set_recording_window(RecordingWindowState.NOT_RECORDING)

    def set_state(self, state: TrayState, *, busy: bool) -> None:
        """アイコン・ヒント・メニューの押せる項目と文言を状態に合わせる。"""
        # 1. 失敗の起動なら、状態を失敗のままにし、録音を押せなくして設定は押せるままにする
        if self._failed:
            self._apply(
                TrayState.FAILED,
                start_text=START_TEXT + FAILED_SUFFIX,
                settings_text=SETTINGS_TEXT,
                start_enabled=False,
                settings_enabled=True,
            )
            return

        # 2. それ以外は、状態の画像とヒントに替え、処理中なら録音と設定を押せなくする
        self._apply(
            state,
            start_text=START_TEXT + (BUSY_SUFFIX if busy else ""),
            settings_text=SETTINGS_TEXT + (BUSY_SUFFIX if busy else ""),
            start_enabled=state is TrayState.IDLE and not busy,
            settings_enabled=not busy,
        )

    def set_failed(self) -> None:
        """文字起こしのエンジンを準備できなかった起動として、アイコンを失敗にする。"""
        self._failed = True
        self.set_state(TrayState.FAILED, busy=False)

    def set_start_hotkey(self, hotkey: str) -> None:
        """「録音を始める」の右に出すホットキー（pynput の書式）を替える。"""
        self._start_hotkey = hotkey
        self._apply_start_text()

    def set_recording_window(self, state: RecordingWindowState) -> None:
        """「録音の画面を出す」の文言・押せるか・太字を、録音の画面の状態に合わせる。"""
        self._window_state = state
        # 1. 隠している間は押せるようにし、アイコンの左クリックと同じ操作の既定の項目として太字にする
        if state is RecordingWindowState.HIDDEN:
            text, enabled = SHOW_WINDOW_TEXT, True
        # 2. それ以外は、状態ごとの理由を添えて押せなくし、太字を外す
        else:
            text, enabled = SHOW_WINDOW_TEXT + SHOW_WINDOW_REASONS[state], False
        self._show_window_action.setText(text)
        self._show_window_action.setEnabled(enabled)
        font = self._show_window_action.font()
        font.setBold(enabled)
        self._show_window_action.setFont(font)

    def show_failure(self, event: FailureEvent, detail: str | None) -> None:
        """知らせの種類の見出しと本文で、警告のアイコンの Windows の通知を出す。通知を押すとログフォルダを開く。"""
        # 押されたときにログフォルダを開くよう、コピーの完了の起こした文字を手放す
        self._copied_text = None
        title = FAILURE_TITLES[event]
        if event == "microphone_unavailable":
            body = MICROPHONE_BODY
        elif event in STARTUP_BODY_FORMATS:
            body = STARTUP_BODY_FORMATS[event].format(reason=detail)
        else:
            body = (f"{detail}。" if detail else "") + FAILURE_BODY_SUFFIXES[event]
        self._icon.showMessage(
            title, body, QSystemTrayIcon.MessageIcon.Warning, MESSAGE_MSEC
        )

    def show_copy_completed(self, text: str) -> None:
        """コピーの完了の見出しと本文で、情報のアイコンの Windows の通知を出す。通知を押すと起こした文字をコピーし直す。"""
        # 押されたときにコピーし直せるよう、起こした文字を持つ（通知には出さない）
        self._copied_text = text
        self._icon.showMessage(
            COPY_COMPLETED_TITLE,
            COPY_COMPLETED_BODY,
            QSystemTrayIcon.MessageIcon.Information,
            MESSAGE_MSEC,
        )

    def hide(self) -> None:
        """トレイのアイコンを消す（処理中に再起動・終了を選んだときと、終わるとき）。"""
        self._icon.hide()

    # --- 内部 ---

    @staticmethod
    def _add_item(menu: QMenu, name: str, text: str) -> QAction:
        """メニューに項目を足し、画面設計の項目 ID を objectName にする。"""
        action = menu.addAction(text)
        action.setObjectName(name)
        return action

    def _apply(
        self,
        state: TrayState,
        *,
        start_text: str,
        settings_text: str,
        start_enabled: bool,
        settings_enabled: bool,
    ) -> None:
        """アイコン・ヒント・メニューの項目の文言と押せるかを反映する。"""
        self._icon.setIcon(self._icons[state])
        self._icon.setToolTip(f"{TOOLTIP_PREFIX}{STATE_NAMES[state]}")
        self._start_label = start_text
        self._apply_start_text()
        self._settings_action.setText(settings_text)
        self._start_action.setEnabled(start_enabled)
        self._settings_action.setEnabled(settings_enabled)
        # 「録音を始める」は押せるときだけ太字にする（既定の項目）
        font = self._start_action.font()
        font.setBold(start_enabled)
        self._start_action.setFont(font)

    def _apply_start_text(self) -> None:
        """「録音を始める」の文言に、右に出すホットキーを付ける（`\\t` の後ろがメニューの右に出る）。"""
        suffix = f"\t{format_hotkey(self._start_hotkey)}" if self._start_hotkey else ""
        self._start_action.setText(self._start_label + suffix)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """アイコンの左クリックは、録音の画面を隠している間は画面を戻し、そうでなければ「録音を始める」が押せるときだけ録音を始める。"""
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        # 隠している: 録音の画面を戻す
        if self._window_state is RecordingWindowState.HIDDEN:
            self.show_window_requested.emit()
        # 待機中: 録音を始める（それ以外の録音から届けるまでの間は何もしない）
        elif self._start_action.isEnabled():
            self.start_requested.emit()

    def _on_message_clicked(self) -> None:
        """通知を押したとき、最後に出した通知がコピーの完了ならコピーし直しを頼み、そうでなければログフォルダを開く。"""
        # コピーの完了: 通知のときに起こした文字でコピーし直す
        if self._copied_text is not None:
            self.recopy_requested.emit(self._copied_text)
        # 失敗の通知: ログフォルダを開く
        else:
            self._open_log_folder()

    def _open_log_folder(self) -> None:
        """ログのフォルダをエクスプローラーで開く。"""
        self._open_folder(self._log_dir)

    @staticmethod
    def _open_folder(folder: Path) -> None:
        """フォルダをエクスプローラーで開く。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
