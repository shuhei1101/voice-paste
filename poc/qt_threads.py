"""PySide6 のイベントループと pynput・uvicorn のスレッドの受け渡し、録音の画面の最前面を確かめる PoC。

`--idle` を付けないと、ドライバーのスレッドが成功条件の操作を順に行い、結果を JSON に書いてトレイの「終了」で終わる。
`--idle` を付けると、待ち受けたまま Ctrl+Break かトレイの「終了」（`--tray-quit-after-ms`）を待つ。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from pynput import keyboard, mouse
from PySide6.QtCore import QObject, QPoint, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

# --- 定数 ---
HOTKEY_PING = "<ctrl>+<alt>+<shift>+<f9>"
HOTKEY_SHOW = "<ctrl>+<alt>+<shift>+<f10>"
HOTKEY_CONFIRM = "<ctrl>+<alt>+<shift>+<f11>"
PING_COUNT = 100
TRIAL_COUNT = 10
PING_GAP_SEC = 0.03
TICK_INTERVAL_MS = 100
KEEP_TOP_INTERVAL_MS = 100
SETTLE_SEC = 0.3
PASTE_SETTLE_SEC = 0.8
PASTE_DELAY_SEC = 0.15
RETURN_TOP_TIMEOUT_SEC = 2.0
POLL_SEC = 0.01
FLICKER_SAMPLE_SEC = 3.0
THREAD_JOIN_TIMEOUT_SEC = 5.0
WAIT_TIMEOUT_SEC = 30.0
WINDOW_SIZE = (360, 140)
WINDOW_BOTTOM_MARGIN = 80

# --- Win32 ---
user32 = ctypes.windll.user32
user32.GetWindow.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.FindWindowW.restype = wintypes.HWND
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.restype = wintypes.HWND
GA_ROOT = 2
GW_HWNDPREV = 3
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
MONITOR_DEFAULTTONEAREST = 2


def find_free_port() -> int:
    """127.0.0.1 の空いているポートを返す。"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def is_above(upper: int, lower: int) -> bool:
    """Z 順で upper が lower より上にあるか（upper から上へ辿って lower に会わなければ上）。"""
    hwnd = user32.GetWindow(upper, GW_HWNDPREV)
    while hwnd:
        if hwnd == lower:
            return False
        hwnd = user32.GetWindow(hwnd, GW_HWNDPREV)
    return True


def keep_on_top(hwnd: int) -> None:
    """フォーカスを取らずに最前面の帯の一番上へ出し直す。"""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def find_window(title: str) -> int:
    """タイトルでウィンドウを探し、出るまで待つ。"""
    deadline = time.monotonic() + WAIT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return int(hwnd)
        time.sleep(POLL_SEC * 10)
    raise TimeoutError(f"ウィンドウが出ない: {title}")


# --- 計測 ---
@dataclass
class Stats:
    """スロットが受けた知らせと、経過時間の表示のタイマーの発火の記録。"""

    received: dict[str, list[tuple[bool, float]]] = field(default_factory=dict)
    ticks: list[float] = field(default_factory=list)

    def record(self, source: str, on_main: bool, latency_ms: float) -> None:
        """知らせを 1 件記録する。"""
        self.received.setdefault(source, []).append((on_main, latency_ms))

    def tick_gaps_ms(self, start: float, end: float) -> list[float]:
        """区間の中のタイマーの発火の間隔を返す。"""
        ticks = [t for t in self.ticks if start <= t <= end]
        return [(b - a) * 1000 for a, b in zip(ticks, ticks[1:], strict=False)]


class UiBridge(QObject):
    """ほかのスレッドからメインスレッドへの Signal。"""

    notified = Signal(str, float)
    command = Signal(object)


class RecordingWindow(QWidget):
    """録音の画面の代わり。最前面で出し、経過時間とボタンを持つ。"""

    def __init__(self, on_confirm: Callable[[str], None], no_focus: bool) -> None:
        """最前面の指定と、確定のボタンを持つ画面を作る。"""
        super().__init__()
        self.setWindowTitle("PoC-録音の画面")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # フォーカスを取らない手段を試すときだけ付ける
        if no_focus:
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(*WINDOW_SIZE)
        self.elapsed = QLabel("0.0 秒")
        self.button = QPushButton("確定")
        self.button.clicked.connect(lambda: on_confirm("button"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.elapsed)
        layout.addWidget(self.button)

    def show_at_cursor(self) -> None:
        """カーソルのあるモニターの作業領域の下中央に出す。"""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = area.x() + (area.width() - self.width()) // 2
        y = area.y() + area.height() - self.height() - WINDOW_BOTTOM_MARGIN
        self.move(x, y)
        self.show()


class Poc:
    """PoC のアプリ。画面・トレイ・ホットキー・API を 1 つのプロセスに並べる。"""

    def __init__(self, args: argparse.Namespace) -> None:
        """Qt のアプリケーションと各スレッドを立てる。"""
        self.args = args
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.stats = Stats()
        self.bridge = UiBridge()
        self.bridge.notified.connect(self.on_notified, Qt.ConnectionType.QueuedConnection)
        self.bridge.command.connect(self.on_command, Qt.ConnectionType.QueuedConnection)
        self.window = RecordingWindow(self.confirm, no_focus=args.no_focus)
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()
        self.shutdown: dict[str, Any] = {}

        # 経過時間の表示のタイマー（固まっていないかの物差し）
        self.started = time.perf_counter()
        self.tick_timer = QTimer()
        self.tick_timer.timeout.connect(self.on_tick)
        # 定期のタイマーが無い場合の終わり方を測るときは、表示のタイマーも止める
        if not args.no_tick:
            self.tick_timer.start(TICK_INTERVAL_MS)

        # 前面を保つ手当て（有効にしたときだけ動かす）
        self.keep_top_timer = QTimer()
        self.keep_top_timer.timeout.connect(lambda: keep_on_top(int(self.window.winId())))

        # Python のシグナルのハンドラを動かすための定期のタイマー（--wake-ms のときだけ）
        if args.wake_ms > 0:
            self.wake_timer = QTimer()
            self.wake_timer.timeout.connect(lambda: None)
            self.wake_timer.start(args.wake_ms)

        self._build_tray()
        self._start_hotkeys()
        self._start_api()
        self.app.aboutToQuit.connect(self.on_about_to_quit)
        signal.signal(signal.SIGBREAK, self.on_break)

    # --- 構成 ---
    def _build_tray(self) -> None:
        """トレイのアイコンと「終了」のメニューを出す。"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.darkCyan)
        self.tray = QSystemTrayIcon(QIcon(pixmap))
        self.menu = QMenu()
        self.quit_action = QAction("終了")
        self.quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def _start_hotkeys(self) -> None:
        """pynput のリスナーのスレッドでホットキーを受ける。ハンドラは Signal を emit するだけ。

        GlobalHotKeys は合成したキー（injected）を無視するため、ドライバーの送るキーでも動くよう
        同じリスナーのスレッドで HotKey を回す。
        """
        hotkeys = [
            keyboard.HotKey(
                keyboard.HotKey.parse(HOTKEY_PING),
                lambda: self.bridge.notified.emit("hotkey", time.perf_counter()),
            ),
            keyboard.HotKey(
                keyboard.HotKey.parse(HOTKEY_SHOW),
                lambda: self.bridge.command.emit(self.window.show_at_cursor),
            ),
            keyboard.HotKey(
                keyboard.HotKey.parse(HOTKEY_CONFIRM),
                lambda: self.bridge.command.emit(lambda: self.confirm("hotkey")),
            ),
        ]

        def on_press(key: keyboard.Key | keyboard.KeyCode | None, _injected: bool) -> None:
            """押されたキーを各ホットキーへ渡す。"""
            for hotkey in hotkeys:
                hotkey.press(self.hotkeys.canonical(key))

        def on_release(key: keyboard.Key | keyboard.KeyCode | None, _injected: bool) -> None:
            """離されたキーを各ホットキーへ渡す。"""
            for hotkey in hotkeys:
                hotkey.release(self.hotkeys.canonical(key))

        self.hotkeys = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkeys.start()

    def _start_api(self) -> None:
        """uvicorn を別のスレッドで動かし、route から Signal を emit する。"""
        api = FastAPI()

        @api.post("/poke")
        def poke() -> dict[str, str]:
            """メインスレッドへ知らせを渡す。"""
            self.bridge.notified.emit("api", time.perf_counter())
            return {"status": "ok"}

        self.api_port = find_free_port()
        config = uvicorn.Config(api, host="127.0.0.1", port=self.api_port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, name="uvicorn")
        self.server_thread.start()

    # --- メインスレッドのスロット ---
    @Slot(str, float)
    def on_notified(self, source: str, emitted: float) -> None:
        """知らせを受けたスレッドと遅れを記録する。"""
        on_main = QThread.currentThread() is self.app.thread()
        self.stats.record(source, on_main, (time.perf_counter() - emitted) * 1000)

    @Slot(object)
    def on_command(self, fn: Callable[[], None]) -> None:
        """ほかのスレッドから渡された画面の操作をメインスレッドで行う。"""
        fn()

    def on_tick(self) -> None:
        """経過時間の表示を進め、発火の時刻を記録する。"""
        now = time.perf_counter()
        self.stats.ticks.append(now)
        self.window.elapsed.setText(f"{now - self.started:.1f} 秒")

    def confirm(self, source: str) -> None:
        """画面を隠し、クリップボードへ書いて、別のスレッドから貼り付けのキーを送る。"""
        self.window.hide()
        QGuiApplication.clipboard().setText(f"{self.pending_token}\n")
        threading.Thread(target=self._send_paste, name=f"paste-{source}").start()

    def _send_paste(self) -> None:
        """少し待ってから Ctrl+V を送る。前面が PoC のウィンドウでなければ、ユーザーのアプリへ送らないよう止める。"""
        time.sleep(PASTE_DELAY_SEC)
        foreground = int(user32.GetForegroundWindow() or 0)
        self.last_paste_foreground = foreground
        if foreground not in self.paste_allowed:
            return
        with self.keyboard.pressed(keyboard.Key.ctrl):
            self.keyboard.tap("v")

    def on_break(self, _signum: int, _frame: object) -> None:
        """Ctrl+Break を受けたらイベントループを抜ける。"""
        self.shutdown["break_received_at"] = time.time()
        self.app.quit()

    def on_about_to_quit(self) -> None:
        """API とホットキーのスレッドを止めて、終わるのを待つ。"""
        self.shutdown["about_to_quit_at"] = time.time()
        self.server.should_exit = True
        self.hotkeys.stop()
        self.server_thread.join(THREAD_JOIN_TIMEOUT_SEC)
        self.hotkeys.join(THREAD_JOIN_TIMEOUT_SEC)
        self.shutdown["threads_alive"] = {
            "uvicorn": self.server_thread.is_alive(),
            "pynput": self.hotkeys.is_alive(),
        }
        self.shutdown["threads_joined_at"] = time.time()
        Path(f"{self.args.out}.shutdown.json").write_text(
            json.dumps(self.shutdown, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def trigger_tray_quit(self) -> None:
        """トレイの「終了」を選んだのと同じ操作をする。"""
        self.shutdown["tray_quit_at"] = time.time()
        self.quit_action.trigger()

    # --- 起動 ---
    def run(self) -> int:
        """待ち受けを始め、ドライバーかアイドルの待ちに入る。"""
        while not self.server.started:
            # 待ち受けに失敗すると uvicorn のスレッドは黙って終わるため、終わっていたら止める
            if not self.server_thread.is_alive():
                raise RuntimeError("API の待ち受けを始められない")
            self.app.processEvents()
            time.sleep(POLL_SEC)
        # アイドルなら準備ができたことだけを知らせて待つ
        if self.args.idle:
            Path(f"{self.args.out}.ready").write_text(str(time.time()), encoding="utf-8")
            if self.args.tray_quit_after_ms > 0:
                QTimer.singleShot(self.args.tray_quit_after_ms, self.trigger_tray_quit)
        else:
            threading.Thread(target=Driver(self).run, name="driver", daemon=True).start()
        return self.app.exec()


class Driver:
    """成功条件の操作を順に行い、結果を記録するスレッド。"""

    def __init__(self, poc: Poc) -> None:
        """PoC のアプリへの参照を持つ。"""
        self.poc = poc
        self.kb = poc.keyboard
        self.results: dict[str, Any] = {}
        self.targets: list[subprocess.Popen[bytes]] = []

    def on_main[T](self, fn: Callable[[], T]) -> T:
        """メインスレッドで fn を実行し、終わるまで待って戻り値を返す。"""
        done = threading.Event()
        box: list[T] = []

        def run() -> None:
            """メインスレッドで動かして結果を渡す。"""
            box.append(fn())
            done.set()

        self.poc.bridge.command.emit(run)
        if not done.wait(WAIT_TIMEOUT_SEC):
            raise TimeoutError("メインスレッドが応答しない")
        return box[0]

    def tap_hotkey(self, last: keyboard.Key) -> None:
        """Ctrl+Alt+Shift+{last} を送る。"""
        with self.kb.pressed(keyboard.Key.ctrl, keyboard.Key.alt, keyboard.Key.shift):
            self.kb.tap(last)

    def activate(self, hwnd: int) -> bool:
        """Alt を送ってから前面へ出し、前面になったかを返す。"""
        self.kb.tap(keyboard.Key.alt)
        user32.SetForegroundWindow(hwnd)
        time.sleep(SETTLE_SEC)
        return int(user32.GetForegroundWindow() or 0) == hwnd

    def spawn_target(self, title: str, *extra: str) -> int:
        """相手のウィンドウのプロセスを立て、ウィンドウのハンドルを返す。"""
        script = Path(__file__).with_name("target.py")
        self.targets.append(subprocess.Popen([sys.executable, str(script), "--title", title, *extra]))
        return find_window(title)

    def run(self) -> None:
        """成功条件を順に確かめ、結果を書いてトレイの「終了」で終わる。"""
        try:
            self.check_tray()
            self.check_pings("hotkey", lambda: self.tap_hotkey(keyboard.Key.f9))
            with httpx.Client(base_url=f"http://127.0.0.1:{self.poc.api_port}") as client:
                self.check_pings("api", lambda: self._post(client))
            self.check_paste()
            self.check_monitors()
            self.check_topmost()
        except Exception as error:  # PoC の最上位: 途中で落ちても結果を残す
            self.results["error"] = repr(error)
        finally:
            for target in self.targets:
                target.terminate()
            Path(self.poc.args.out).write_text(
                json.dumps(self.results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.on_main(self.poc.trigger_tray_quit)

    def _post(self, client: httpx.Client) -> None:
        """API を 1 回呼び、応答の状態を記録する。"""
        self.results.setdefault("api_status", []).append(client.post("/poke").status_code)

    # --- 各成功条件 ---
    def check_tray(self) -> None:
        """トレイが使え、アイコンとメニューが出ているか。"""
        self.results["tray"] = self.on_main(
            lambda: {
                "available": QSystemTrayIcon.isSystemTrayAvailable(),
                "visible": self.poc.tray.isVisible(),
                "geometry": self.poc.tray.geometry().getRect(),
                "menu_actions": [a.text() for a in self.poc.menu.actions()],
            }
        )

    def check_pings(self, source: str, send: Callable[[], None]) -> None:
        """知らせを 100 回送り、メインスレッドで受けたか・遅れ・タイマーの間隔を記録する。"""
        start = time.perf_counter()
        for _ in range(PING_COUNT):
            send()
            time.sleep(PING_GAP_SEC)
        deadline = time.monotonic() + WAIT_TIMEOUT_SEC
        while len(self.poc.stats.received.get(source, [])) < PING_COUNT and time.monotonic() < deadline:
            time.sleep(POLL_SEC)
        end = time.perf_counter()
        received = self.poc.stats.received.get(source, [])
        latencies = [lat for _, lat in received]
        gaps = self.poc.stats.tick_gaps_ms(start, end)
        self.results[f"{source}_pings"] = {
            "received": len(received),
            "on_main": sum(1 for on_main, _ in received if on_main),
            "latency_max_ms": max(latencies, default=None),
            "latency_median_ms": statistics.median(latencies) if latencies else None,
            "tick_gap_max_ms": max(gaps, default=None),
        }

    def check_paste(self) -> None:
        """貼り付け先にフォーカスがある状態から、確定した文字が貼り付け先へ入るか。"""
        out = Path(self.poc.args.out).with_name("paste_target.txt")
        out.unlink(missing_ok=True)
        target = self.spawn_target("PoC-貼り付け先", "--out", str(out))
        self.poc.paste_allowed.add(target)
        for via in ("hotkey", "button"):
            trials = []
            for i in range(TRIAL_COUNT):
                token = f"{via}-{i}"
                self.poc.pending_token = token
                focused = self.activate(target)
                self.tap_hotkey(keyboard.Key.f10)
                time.sleep(SETTLE_SEC)
                fg_after_show = int(user32.GetForegroundWindow() or 0)
                # 確定の入口ごとに確定する
                if via == "hotkey":
                    self.tap_hotkey(keyboard.Key.f11)
                else:
                    center = self.on_main(
                        lambda: self.poc.window.button.mapToGlobal(self.poc.window.button.rect().center())
                    )
                    self._click(center)
                time.sleep(PASTE_SETTLE_SEC)
                text = out.read_text(encoding="utf-8") if out.exists() else ""
                trials.append(
                    {
                        "focused_before": focused,
                        "foreground_after_show": self._name(fg_after_show, target),
                        "foreground_at_paste": self._name(self.poc.last_paste_foreground, target),
                        "pasted": token in text,
                    }
                )
            self.results[f"paste_{via}"] = trials

    def _name(self, hwnd: int, target: int) -> str:
        """前面のウィンドウを、貼り付け先・録音の画面・それ以外で呼び分ける。"""
        if hwnd == target:
            return "target"
        if hwnd == int(self.poc.window.winId()):
            return "recording_window"
        return "other"

    def _click(self, point: QPoint) -> None:
        """論理座標の点を物理座標に直してクリックする。"""
        ratio = self.on_main(lambda: QGuiApplication.screenAt(point).devicePixelRatio())
        screen_geo = self.on_main(lambda: QGuiApplication.screenAt(point).geometry())
        x = screen_geo.x() + (point.x() - screen_geo.x()) * ratio
        y = screen_geo.y() + (point.y() - screen_geo.y()) * ratio
        self.poc.mouse.position = (int(x), int(y))
        time.sleep(POLL_SEC * 5)
        # 押す点にあるのが録音の画面でなければ、ユーザーのアプリを押さないよう止める
        hit = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(int(x), int(y))), GA_ROOT)
        if int(hit or 0) != int(self.poc.window.winId()):
            self.results.setdefault("click_skipped", 0)
            self.results["click_skipped"] += 1
            return
        self.poc.mouse.click(mouse.Button.left)

    def check_monitors(self) -> None:
        """カーソルを各モニターに置いて出し、そのモニターの作業領域の中に出るか。"""
        screens = self.on_main(
            lambda: [
                (s.name(), s.geometry().center(), s.devicePixelRatio())
                for s in QGuiApplication.screens()
            ]
        )
        trials = []
        for name, center, ratio in screens:
            self.on_main(lambda c=center: QCursor.setPos(c))
            time.sleep(SETTLE_SEC)
            self.tap_hotkey(keyboard.Key.f10)
            time.sleep(SETTLE_SEC)
            inside = self.on_main(
                lambda: QGuiApplication.screenAt(QCursor.pos())
                .availableGeometry()
                .contains(self.poc.window.frameGeometry())
            )
            # Qt と独立に Win32 でも、ウィンドウとカーソルが同じモニターかを確かめる
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            cursor_monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
            window_monitor = user32.MonitorFromWindow(
                int(self.poc.window.winId()), MONITOR_DEFAULTTONEAREST
            )
            trials.append(
                {
                    "screen": name,
                    "device_pixel_ratio": ratio,
                    "inside_available_geometry": inside,
                    "same_monitor_win32": cursor_monitor == window_monitor,
                }
            )
            self.on_main(self.poc.window.hide)
        self.results["monitors"] = trials

    def check_topmost(self) -> None:
        """ほかの最前面のウィンドウを前面へ出したときと、出し直したときの Z 順。"""
        rec = int(self.poc.window.winId())
        other = self.spawn_target("PoC-最前面の相手", "--topmost", "--geometry", "300,300,600,400")
        self.on_main(self.poc.window.show_at_cursor)
        time.sleep(SETTLE_SEC)

        # 手当てなし: 前面へ出した直後の Z 順
        no_fix = []
        for _ in range(TRIAL_COUNT):
            self.activate(other)
            no_fix.append(is_above(rec, other))
        self.results["topmost_other_no_fix"] = no_fix

        # 手当てあり: 前面へ出してから録音の画面が上へ戻るまでの時間
        self.on_main(lambda: self.poc.keep_top_timer.start(KEEP_TOP_INTERVAL_MS))
        with_fix = []
        for _ in range(TRIAL_COUNT):
            self.kb.tap(keyboard.Key.alt)
            user32.SetForegroundWindow(other)
            start = time.perf_counter()
            returned_ms = None
            while time.perf_counter() - start < RETURN_TOP_TIMEOUT_SEC:
                if is_above(rec, other) and time.perf_counter() - start > POLL_SEC:
                    returned_ms = (time.perf_counter() - start) * 1000
                    break
                time.sleep(POLL_SEC)
            with_fix.append(returned_ms)
            time.sleep(SETTLE_SEC)
        self.results["topmost_other_with_fix_return_ms"] = with_fix

        # 取り合う相手（同じく一定の間隔で最前面を取り直す）とのちらつき
        fighter = self.spawn_target("PoC-取り合う相手", "--topmost", "--fight", "--geometry", "350,350,600,400")
        flips = 0
        last = is_above(rec, fighter)
        end = time.monotonic() + FLICKER_SAMPLE_SEC
        while time.monotonic() < end:
            now = is_above(rec, fighter)
            flips += int(now != last)
            last = now
            time.sleep(POLL_SEC)
        self.results["topmost_fight_flips_in_3s"] = flips
        self.targets.pop().terminate()
        self.on_main(self.poc.keep_top_timer.stop)

        # 出し直し: 隠して出し直した直後に、最前面の相手より上か
        reshow = []
        for _ in range(TRIAL_COUNT):
            self.on_main(self.poc.window.hide)
            time.sleep(SETTLE_SEC)
            self.tap_hotkey(keyboard.Key.f10)
            time.sleep(SETTLE_SEC)
            reshow.append(is_above(rec, other))
        self.results["topmost_reshow"] = reshow
        self.on_main(self.poc.window.hide)


def main() -> int:
    """引数を読み、PoC のアプリを動かす。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--wake-ms", type=int, default=0)
    parser.add_argument("--tray-quit-after-ms", type=int, default=0)
    parser.add_argument("--no-focus", action="store_true")
    parser.add_argument("--no-tick", action="store_true")
    poc = Poc(parser.parse_args())
    poc.pending_token = ""
    poc.paste_allowed = {int(poc.window.winId())}
    poc.last_paste_foreground = 0
    return poc.run()


if __name__ == "__main__":
    sys.exit(main())