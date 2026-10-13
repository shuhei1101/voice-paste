"""常駐アプリを pytest のプロセスの中で `main()` から起動し、トレイ・画面をイベントで操作・観測する、画面・トレイの E2E の補助。

実機のマウス・キーボードは使わず、Windows のシェル（タスクバーのトレイ・通知・エクスプローラー）は読まない。
`--data-dir` の一時フォルダで、Qt は offscreen のまま起動し、起動・設定の読み込み・文字起こしワーカー・API・片付けは本物を通す。
`main()` が受ける `exec_loop` でケースの操作をイベントループの中で進める。
トレイのメニューは項目の `QAction` を trigger し、画面のボタン・欄はクリックとキーを Qt のイベントで渡す。
`main()` の中で作られるトレイ（`Tray`）は作ったものを控え、ホットキーの受付（`HotkeyListener`）は何も始めない受け手に、
フォルダを開く呼び出し（`QDesktopServices`）は渡されたパスを控えるものに差し替える。
動いている常駐アプリの補正（`SessionDeps` の `correct`）は、渡された関数を控える（本物の補正のまま。マイクを開かずに文字を渡して確かめる）。
"""

from __future__ import annotations

import logging
import os
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)

import voice_paste.main as main_module
import voice_paste.ui.tray as tray_module
from tests.support.processes import ProcessInfo, kill_tree, process_table, processes_with
from tests.support.real_service import (
    LOOPBACK,
    QT_PLATFORM_ENV,
    QT_PLATFORM_OFFSCREEN,
    REQUEST_TIMEOUT_SEC,
    SOURCE_DIR,
    free_port,
    post_to_api,
    read_log_records,
    read_token_file,
    settings_text,
)
from voice_paste.integrations.whisper.client import WORKER_MODULE
from voice_paste.ui.tray import STATE_NAMES, TOOLTIP_PREFIX, Tray, TrayState

SERVICE_COMMAND = "-m voice_paste"
"""常駐アプリのコマンドラインに含まれる言葉（venv の python.exe は本体のプロセスを子に持つ）。"""

IDLE = STATE_NAMES[TrayState.IDLE]
FAILED = STATE_NAMES[TrayState.FAILED]
"""トレイのヒントの状態の名前。"""

UI_TIMEOUT_SEC = 20.0
"""画面・メニューが出る・消える、状態が変わるのを待つ上限。"""

EXIT_TIMEOUT_SEC = 30.0
"""ケースが終わった後、常駐アプリが自分でイベントループを抜けるのを待つ上限。"""

POLL_MS = 10
"""待っている間にイベントを処理する間隔（ミリ秒）。"""

DIALOG_WATCH_MS = 20
"""出てはいけない確認ダイアログを見張る間隔（ミリ秒）。"""

MILLISECONDS_PER_SECOND = 1000

WidgetT = TypeVar("WidgetT", bound=QWidget)

type Case = Callable[[ResidentApp], None]
"""イベントループの中で進めるケースの操作と検証。"""


# === 別プロセスの常駐アプリ ===


def service_processes_for(data_dir: Path) -> list[ProcessInfo]:
    """data_dir で動いている常駐アプリのプロセス（再起動で起動し直したものを含む）を返す。"""
    return [
        p
        for p in process_table()
        if SERVICE_COMMAND in p.command_line
        and str(data_dir) in p.command_line
        and WORKER_MODULE not in p.command_line
    ]


def kill_service_processes_for(data_dir: Path) -> None:
    """data_dir で動いている常駐アプリ（再起動で起動し直したものを含む）を全て止める。"""
    for process in service_processes_for(data_dir):
        kill_tree(process.pid)


# === main() の中で作られるものの差し替え ===


class FakeHotkeyListener:
    """HotkeyListener の代わり。ホットキーの受付は始めず、登録された関数を控える。"""

    def __init__(self, *, accept_injected: bool = False) -> None:
        self.accept_injected = accept_injected
        self.bindings: dict[str, Callable[[], None]] = {}
        self.start_count = 0

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """登録するホットキーと関数を控える。"""
        self.bindings = dict(bindings)
        self.start_count += 1

    def stop(self) -> None:
        """受付は始めていないため、何もしない。"""


def _fake_desktop_services(opened: list[Path]) -> type:
    """フォルダを開く呼び出しを、渡されたパスを opened に控えるだけのものに差し替える QDesktopServices を返す。"""

    class FakeDesktopServices:
        """QDesktopServices の代わり。エクスプローラーは開かない。"""

        @staticmethod
        def openUrl(url: QUrl) -> bool:  # noqa: N802 Qt の名前
            """開くはずだったフォルダのパスを控える。"""
            opened.append(Path(url.toLocalFile()))
            return True

    return FakeDesktopServices


# === イベントループの中の常駐アプリ ===


class ResidentApp:
    """`main()` で起動した常駐アプリ。ケースの中ではトレイ・画面を操作・観測し、`main()` が戻った後は結果を持つ。"""

    def __init__(self, data_dir: Path, port: int) -> None:
        self.data_dir = data_dir
        self.port = port
        self.tray: Tray | None = None
        self.hotkeys: FakeHotkeyListener | None = None
        self.correct: Callable[[str], str] | None = None
        self.opened_folders: list[Path] = []
        self.unexpected_dialogs: list[str] = []
        self.worker_pids_at_start: set[int] = set()
        self.case_finished = False
        self.exit_code: int | None = None
        self.exited_by_itself = False
        self._expected_dialogs: set[str] = set()

    # --- 待つ ---

    @staticmethod
    def wait_until(condition: Callable[[], object], timeout_sec: float = UI_TIMEOUT_SEC) -> bool:
        """condition が真になるか timeout_sec が過ぎるまで、イベントを処理しながら待ち、真になったかを返す。"""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if condition():
                return True
            QTest.qWait(POLL_MS)
        return bool(condition())

    # --- トレイ ---

    def _icon(self) -> QSystemTrayIcon:
        """トレイのアイコン（`Tray` が持つ QSystemTrayIcon）を返す。"""
        assert self.tray is not None, "トレイがまだ作られていない"
        icon = self.tray.findChild(QSystemTrayIcon)
        assert icon is not None, "トレイのアイコンが無い"
        return icon

    def tray_state(self) -> str:
        """トレイのアイコンのヒントの状態の名前（待機中・録音中など）。"""
        return self._icon().toolTip().removeprefix(TOOLTIP_PREFIX)

    def tray_visible(self) -> bool:
        """トレイのアイコンが出ているか。"""
        return self._icon().isVisible()

    def _menu_action(self, item: str) -> QAction:
        """トレイのメニューの項目 ID（menu_start など）の項目を引く。"""
        menu = self._icon().contextMenu()
        for action in menu.actions():
            if action.objectName() == item:
                return action
        raise AssertionError(f"トレイのメニューに {item} が無い")

    def choose_tray_menu(self, item: str) -> None:
        """トレイのメニューの項目を選ぶ（項目の QAction を trigger する）。押せない項目は失敗させる。"""
        action = self._menu_action(item)
        assert action.isEnabled(), f"トレイのメニューの {item} は押せない"
        action.trigger()

    def menu_item_enabled(self, item: str) -> bool:
        """トレイのメニューの項目が押せるか。"""
        return self._menu_action(item).isEnabled()

    # --- API・ログ・プロセス ---

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """トークンのファイルに書かれたポートの API へ POST する。authorized ならトークンのファイルのトークンを付ける。"""
        info = read_token_file(self.data_dir)
        assert info is not None, "トークンのファイルが読めない"
        with httpx.Client(
            base_url=f"http://{LOOPBACK}:{info['port']}", timeout=REQUEST_TIMEOUT_SEC
        ) as http:
            return post_to_api(
                http,
                str(info["token"]),
                path,
                json_body=json_body,
                headers=headers,
                authorized=authorized,
            )

    def log_messages(self, level: str | None = None) -> list[str]:
        """常駐アプリのログの文（msg）を、level（無ければ全て）で絞って並べる。"""
        return [
            str(record["msg"])
            for record in read_log_records(self.data_dir)
            if level is None or record["level"] == level
        ]

    def notified(self, event: str) -> bool:
        """ユーザーへの知らせ（notify）のログに、event（api_unavailable など）が書かれているか。"""
        return any(f"ユーザーへの知らせ（{event}" in message for message in self.log_messages())

    @staticmethod
    def worker_pids() -> set[int]:
        """この pytest のプロセスが起こした文字起こしワーカーのプロセス（ランチャーと本体）の番号。"""
        return {p.pid for p in processes_with(WORKER_MODULE, os.getpid())}

    def remaining_workers(self) -> list[int]:
        """起動したときに動いていた文字起こしワーカーのうち、今も動いているものの番号を並べる。"""
        alive = {p.pid for p in process_table()}
        return sorted(self.worker_pids_at_start & alive)

    # --- 画面 ---

    @staticmethod
    def _visible_widgets(name: str, cls: type[WidgetT]) -> list[WidgetT]:
        """出ている部品のうち、項目 ID（objectName）が name のものを並べる。"""
        return [
            widget
            for widget in QApplication.allWidgets()
            if isinstance(widget, cls) and widget.objectName() == name and widget.isVisible()
        ]

    def window(self, name: str) -> QWidget | None:
        """出ている画面・部品を項目 ID で引く。無ければ None。"""
        found = self._visible_widgets(name, QWidget)
        return found[0] if found else None

    def wait_widget(
        self, name: str, cls: type[WidgetT], timeout_sec: float = UI_TIMEOUT_SEC
    ) -> WidgetT:
        """出ている部品が出るのを待って返す。出なければテストを失敗させる。"""
        assert self.wait_until(lambda: self._visible_widgets(name, cls), timeout_sec), (
            f"{name} が出なかった"
        )
        return self._visible_widgets(name, cls)[0]

    def wait_window_gone(self, name: str, timeout_sec: float = UI_TIMEOUT_SEC) -> bool:
        """画面が消えるのを待ち、消えたかを返す。"""
        return self.wait_until(lambda: self.window(name) is None, timeout_sec)

    def press(self, name: str) -> None:
        """項目 ID のボタンをクリックする。"""
        QTest.mouseClick(self.wait_widget(name, QPushButton), Qt.MouseButton.LeftButton)

    def click(self, name: str) -> None:
        """項目 ID のボタン・ラジオボタン・チェックボックスをクリックする。"""
        QTest.mouseClick(self.wait_widget(name, QAbstractButton), Qt.MouseButton.LeftButton)

    def label(self, name: str) -> str:
        """項目 ID のラベルの文字を返す。"""
        return self.wait_widget(name, QLabel).text()

    # --- 補正 ---

    def correct_text(self, text: str) -> str:
        """動いている常駐アプリの補正に文字を渡し、補正した文字を返す（その時点の設定の用語集で補正する）。"""
        assert self.correct is not None, "常駐アプリの補正がまだ作られていない（エンジンを準備できなかった）"
        return self.correct(text)

    # --- 確認ダイアログ ---

    @contextmanager
    def answering(self, dialog_name: str, button_name: str) -> Iterator[None]:
        """この中で出る確認ダイアログ（exec で止まる）の button_name のボタンをクリックする。ダイアログが出なければ失敗させる。"""
        self._expected_dialogs.add(dialog_name)
        answered: list[bool] = []
        timer = QTimer()

        def _click() -> None:
            """ダイアログが出ていれば、その中のボタンをクリックして見張りを止める。"""
            box = QApplication.activeModalWidget()
            if isinstance(box, QMessageBox) and box.objectName() == dialog_name:
                button = box.findChild(QPushButton, button_name)
                if button is not None:
                    timer.stop()
                    answered.append(True)
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        timer.timeout.connect(_click)
        timer.start(POLL_MS)
        try:
            yield
        finally:
            timer.stop()
            self._expected_dialogs.discard(dialog_name)
        assert answered, f"{dialog_name} の {button_name} を押せなかった（ダイアログが出なかった）"

    def watch_dialogs(self) -> None:
        """予約していない確認ダイアログが出ていれば、止まらないよう閉じて控える。"""
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox) and box.objectName() not in self._expected_dialogs:
            self.unexpected_dialogs.append(box.objectName())
            box.reject()

    # --- 設定画面 ---

    def open_settings(self) -> None:
        """トレイの「設定…」から設定画面を開く。"""
        self.choose_tray_menu("menu_settings")
        self.wait_widget("settings_window", QWidget)

    def select_group(self, name: str) -> None:
        """設定画面のまとまりのメニューから、まとまりをクリックして選ぶ。"""
        menu = self.wait_widget("group_menu", QListWidget)
        items = menu.findItems(name, Qt.MatchFlag.MatchExactly)
        assert items, f"まとまり {name} が見つからない"
        QTest.mouseClick(
            menu.viewport(), Qt.MouseButton.LeftButton, pos=menu.visualItemRect(items[0]).center()
        )
        assert self.wait_until(lambda: menu.currentItem() is items[0]), f"まとまり {name} を選べない"

    def set_field(self, key: str, text: str) -> None:
        """設定画面の文字の欄（field_{キー}）をクリックし、入っている文字を選んでから文字を打つ。"""
        self.set_text(f"field_{key}", text)

    def set_text(self, name: str, text: str) -> None:
        """項目 ID の文字の欄をクリックし、入っている文字を選んでから文字を打つ。"""
        edit = self.wait_widget(name, QLineEdit)
        QTest.mouseClick(edit, Qt.MouseButton.LeftButton)
        edit.selectAll()
        QTest.keyClicks(edit, text)

    def field_value(self, key: str) -> str:
        """設定画面の文字の欄の今の文字を返す。"""
        return self.wait_widget(f"field_{key}", QLineEdit).text()


# === 起動 ===


@contextmanager
def _restored_process_state(qapp: QApplication) -> Iterator[None]:
    """`main()` が入れた SIGINT・SIGBREAK のハンドラ、ルートロガーのハンドラ・レベル、スタイルシートを、終わったら元に戻す。"""
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level
    signals = (signal.SIGINT, signal.SIGBREAK)
    signal_handlers_before = {number: signal.getsignal(number) for number in signals}
    style_before = qapp.styleSheet()
    try:
        yield
    finally:
        # main が足したハンドラ（日付ごとのログのファイル・標準エラー）は閉じて外す
        for handler in list(root.handlers):
            if handler not in handlers_before:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level_before)
        for number, handler_before in signal_handlers_before.items():
            if handler_before is not None:
                signal.signal(number, handler_before)
        qapp.setStyleSheet(style_before)


def _spy_on_main(app: ResidentApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """`main()` が作るトレイ・ホットキーの受付・フォルダを開く呼び出し・補正を、控える・始めない・開かない・控えるものに差し替える。"""

    def make_tray(settings_dir: Path, log_dir: Path) -> Tray:
        """本物のトレイを作り、控える。"""
        app.tray = Tray(settings_dir, log_dir)
        return app.tray

    def make_hotkey_listener(*, accept_injected: bool = False) -> FakeHotkeyListener:
        """ホットキーの受付の代わりを作り、控える。"""
        app.hotkeys = FakeHotkeyListener(accept_injected=accept_injected)
        return app.hotkeys

    session_deps = main_module.SessionDeps

    def make_session_deps(**fields: Any) -> Any:
        """本物の SessionDeps を作り、渡された補正の関数を控える。"""
        app.correct = fields["correct"]
        return session_deps(**fields)

    monkeypatch.setattr(main_module, "Tray", make_tray)
    monkeypatch.setattr(main_module, "HotkeyListener", make_hotkey_listener)
    monkeypatch.setattr(main_module, "SessionDeps", make_session_deps)
    monkeypatch.setattr(tray_module, "QDesktopServices", _fake_desktop_services(app.opened_folders))
    # 文字起こしワーカーと再起動で起こす新しいプロセスが、この作業ツリーの src を読むようにする
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_DIR))
    monkeypatch.setenv(QT_PLATFORM_ENV, QT_PLATFORM_OFFSCREEN)


def run_resident_app(
    case: Case,
    *,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
    extra_settings: str = "",
    port: int | None = None,
    prepare: Callable[[Path], None] | None = None,
    expect_exit: bool = False,
) -> ResidentApp:
    """常駐アプリを `main()` から起動し、イベントループの中で case を進めて、`main()` が戻った後の ResidentApp を返す。

    prepare は起動の前に data_dir へファイルを用意する関数。
    expect_exit が真のときは、case が終わった後に常駐アプリが自分でイベントループを抜けるのを待つ
    （EXIT_TIMEOUT_SEC までに抜けなければ止めて、exited_by_itself を偽にする）。偽のときは case が終わったらすぐ止める。
    case が失敗したら、片付けた後にその失敗を出し直す。
    """
    # 1. 設定を置き、差し替えを入れる
    data_dir.mkdir(parents=True, exist_ok=True)
    if prepare is not None:
        prepare(data_dir)
    api_port = free_port() if port is None else port
    (data_dir / "settings.toml").write_text(settings_text(api_port, extra_settings), encoding="utf-8")
    app = ResidentApp(data_dir, api_port)
    _spy_on_main(app, monkeypatch)
    failures: list[BaseException] = []

    # 2. イベントループの中で case を進める（case が終わったら、止めるか、自分で抜けるのを待つ）
    def exec_loop(application: QApplication) -> int:
        """ダイアログの見張りを始め、case を最初のイベントで進め、イベントループを回す。"""
        watcher = QTimer()
        watcher.timeout.connect(app.watch_dialogs)
        watcher.start(DIALOG_WATCH_MS)
        exit_limit = QTimer()
        exit_limit.setSingleShot(True)

        def stop_waiting_for_exit() -> None:
            """常駐アプリが自分で抜けなかったため、止める。"""
            app.exited_by_itself = False
            application.quit()

        exit_limit.timeout.connect(stop_waiting_for_exit)

        def run_case() -> None:
            """case を進める。失敗は控える。"""
            app.worker_pids_at_start = app.worker_pids()
            try:
                case(app)
                app.case_finished = True
            except BaseException as error:  # noqa: BLE001 slot の中の失敗を main の後に出し直す
                failures.append(error)
            # 抜ける依頼を待つか、すぐ止めるか
            if expect_exit and not failures:
                app.exited_by_itself = True
                exit_limit.start(int(EXIT_TIMEOUT_SEC * MILLISECONDS_PER_SECOND))
            else:
                application.quit()

        QTimer.singleShot(0, run_case)
        try:
            return application.exec()
        finally:
            watcher.stop()
            exit_limit.stop()

    with _restored_process_state(qapp):
        app.exit_code = main_module.main(["--data-dir", str(data_dir)], exec_loop=exec_loop)

    # 3. case の失敗があれば出し直す
    if failures:
        raise failures[0]
    assert app.case_finished, "ケースが実行されなかった"
    return app
