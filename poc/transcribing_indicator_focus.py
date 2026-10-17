"""文字起こし中の表示が実機の Windows で前面を奪わず、見出しの行のドラッグで動くかを確かめる PoC。

常駐アプリを `main()` から実機の画面（offscreen でない）に出して起動し、メモ帳を前面に置いたまま、
実物のマウスで切り替えのボタンを押し、見出しの行をつかんで動かして、前面の窓・メモ帳の本文・クリップボード・窓の位置を読む。
差し替えるのは、録音の入力（SAPI の WAV）・システム音量・文字起こしの戻りの遅れ・ホットキーの受付だけ。
結果は poc/results/ に JSON と画像で書く。

実行（リポジトリの直下で）: .venv/Scripts/python.exe poc/transcribing_indicator_focus.py
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import pyperclip
import win32api
import win32con
import win32gui
import win32process
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel, QWidget

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import voice_paste.main as main_module  # noqa: E402 リポジトリの直下を sys.path に足した後に読む
from tests.support.inprocess import VolumeLog, WavInput, read_wav, synthesize_speech  # noqa: E402
from tests.support.real_service import UNUSED_START_HOTKEY, free_port, settings_text  # noqa: E402
from voice_paste.ui.windows.transcribing_indicator import (  # noqa: E402
    CHECK_BADGE_MARGIN_PX,
    CHECK_BADGE_SIZE_PX,
    SwitchButton,
)
from voice_paste.ui.windows.window_parts import HeadRow  # noqa: E402

RESULTS_DIR = REPO_ROOT / "poc" / "results"
"""結果の JSON と画像を置く場所。"""

SPEECH_TEXT = "今日は晴れているので、午後から散歩に出かけます。"
"""録音の入力に流す文。"""

TRANSCRIBE_DELAY_SEC = 8.0
"""押す・動かす間を取るため、文字起こしの戻りを遅らせる時間。"""

STARTUP_TIMEOUT_SEC = 300.0
"""常駐アプリが起動してホットキーを登録するまでを待つ上限（文字起こしのモデルを読む時間を含む）。"""

UI_TIMEOUT_SEC = 30.0
"""録音の始まり・文字起こし中の表示が出るのを待つ上限。"""

DELIVER_TIMEOUT_SEC = 120.0
"""確定してから届け終えるまでを待つ上限。"""

SETTLE_SEC = 0.5
"""押した・放した後に、前面と画面が落ち着くのを待つ時間。"""

AFTER_DELIVER_SEC = 2.0
"""文字起こし中の表示が閉じた後、貼り付けのキーが届くのを待つ時間。"""

POLL_SEC = 0.1
"""待っている間に状態を読み直す間隔。"""

CLICK_HOLD_SEC = 0.05
"""押してから放すまでの時間。"""

DRAG_DISTANCE_PX = 200
"""見出しの行をつかんで動かす距離（実機の画素）。"""

DRAG_STEPS = 20
"""動かす距離を分ける回数。"""

DRAG_SAMPLE_EVERY = 2
"""何回動かすごとに窓の位置を読むか（20 回動かして 10 回読む）。"""

DRAG_STEP_WAIT_SEC = 0.1
"""動かすたびに、OS の移動のループが窓を動かすのを待つ時間。"""

DRAG_PRESS_WAIT_SEC = 0.3
"""つかんでから動かし始めるまでの時間。"""

FOLLOW_TOLERANCE_PX = 2
"""窓の左上とカーソルの差が、つかんだときの差からずれてよい幅。"""

HEAD_ROW_GRAB_RATIO = 0.6
"""見出しの行のどこをつかむか（左端からの幅の割合。状態の文字の右の、何も無いところ）。"""

NOTEPAD_TIMEOUT_SEC = 10.0
"""メモ帳の窓が出るのを待つ上限。"""

CLIPBOARD_SENTINEL = "voice-paste-poc-clipboard-sentinel"
"""録音の前にクリップボードへ置く目印。"""

NORMALIZED_MAX = 65535
"""SendInput の絶対座標の最大値。"""

NOTEPAD_EDIT_CLASS = "RichEditD2DPT"
"""Microsoft Store 版のメモ帳の入力欄のクラス名。"""

NOTEPAD_TEXT_LIMIT = 4096
"""メモ帳の本文を読む上限の文字数。"""

_user32 = ctypes.windll.user32
_user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
_user32.SendMessageW.restype = ctypes.c_ssize_t


class _GuiThreadInfo(ctypes.Structure):
    """GetGUIThreadInfo が書く GUITHREADINFO。"""

    _fields_: ClassVar = [
        ("cbSize", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.c_long * 4),
    ]


# === Windows の操作と観測 ===


def foreground() -> int:
    """前面の窓のハンドル。"""
    return win32gui.GetForegroundWindow()


def bring_to_front(hwnd: int) -> None:
    """窓を前面にする（Alt を押して放し、前面の切り替えの制限を外してから頼む）。"""
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(SETTLE_SEC)


def _windows_titled(part: str) -> list[int]:
    """タイトルに part を含む最上位の窓。"""
    found: list[int] = []
    win32gui.EnumWindows(
        lambda hwnd, _: found.append(hwnd) if part in win32gui.GetWindowText(hwnd) else None, None
    )
    return found


def _notepad_edit(hwnd: int) -> int:
    """メモ帳の窓の入力欄のハンドル。"""
    edits: list[int] = []
    win32gui.EnumChildWindows(
        hwnd,
        lambda child, _: edits.append(child)
        if win32gui.GetClassName(child) == NOTEPAD_EDIT_CLASS
        else None,
        None,
    )
    if not edits:
        raise RuntimeError("メモ帳の入力欄が見つからない")
    return edits[0]


@dataclass
class Notepad:
    """検証用に開いたメモ帳の窓と入力欄。"""

    hwnd: int
    edit: int
    path: Path

    def text(self) -> str:
        """入力欄の本文を WM_GETTEXT で読む。"""
        buffer = ctypes.create_unicode_buffer(NOTEPAD_TEXT_LIMIT)
        _user32.SendMessageW(self.edit, win32con.WM_GETTEXT, NOTEPAD_TEXT_LIMIT, ctypes.addressof(buffer))
        return buffer.value

    def all_texts(self) -> list[str]:
        """窓の中の全ての入力欄（タブごと）の本文を読む。"""
        edits: list[int] = []
        win32gui.EnumChildWindows(
            self.hwnd,
            lambda child, _: edits.append(child)
            if win32gui.GetClassName(child) == NOTEPAD_EDIT_CLASS
            else None,
            None,
        )
        return [Notepad(hwnd=self.hwnd, edit=edit, path=self.path).text() for edit in edits]

    def focused_class(self) -> str:
        """メモ帳の窓のスレッドで、キーボードのフォーカスを持つ部品のクラス名。"""
        thread_id, _ = win32process.GetWindowThreadProcessId(self.hwnd)
        info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
        _user32.GetGUIThreadInfo(thread_id, ctypes.byref(info))
        focus = info.hwndFocus
        return win32gui.GetClassName(focus) if focus else ""

    def clear(self) -> None:
        """入力欄を空にする。"""
        empty = ctypes.create_unicode_buffer("")
        _user32.SendMessageW(self.edit, win32con.WM_SETTEXT, 0, ctypes.addressof(empty))

    def close(self) -> None:
        """本文を空にしてから窓を閉じる（保存を尋ねさせない）。"""
        self.clear()
        win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)


def open_notepad(name: str) -> Notepad:
    """空のファイルを新しいメモ帳で開き、そのファイルの名前をタイトルに持つ窓と入力欄を控える。"""
    path = Path(tempfile.gettempdir()) / f"{name}.txt"
    path.write_text("", encoding="utf-8")
    subprocess.Popen(["notepad.exe", str(path)])  # noqa: S603, S607 検証用のメモ帳を開く
    deadline = time.monotonic() + NOTEPAD_TIMEOUT_SEC
    while time.monotonic() < deadline:
        windows = _windows_titled(name)
        if windows:
            hwnd = windows[0]
            return Notepad(hwnd=hwnd, edit=_notepad_edit(hwnd), path=path)
        time.sleep(POLL_SEC)
    raise RuntimeError(f"メモ帳の窓が出なかった（{name}）")


def _move_cursor(x: int, y: int) -> None:
    """実物のマウスを、実機の画素の座標へ SendInput の絶対座標で動かす。"""
    width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    win32api.mouse_event(
        win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE,
        round(x * NORMALIZED_MAX / (width - 1)),
        round(y * NORMALIZED_MAX / (height - 1)),
    )


def click(x: int, y: int) -> None:
    """実物のマウスで (x, y) を左クリックする。"""
    _move_cursor(x, y)
    time.sleep(CLICK_HOLD_SEC)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(CLICK_HOLD_SEC)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)


@dataclass
class DragResult:
    """見出しの行をつかんで動かした結果。"""

    offset_at_press: tuple[int, int]
    offsets_while_moving: list[tuple[int, int]]
    max_deviation_px: int
    moved_px: tuple[int, int]


def drag(hwnd: int, x: int, y: int) -> DragResult:
    """(x, y) をつかんで右へ DRAG_DISTANCE_PX 動かし、動かす間の窓の左上とカーソルの差と、動いた距離を返す。"""
    # 1. つかむ前の窓の位置と、つかんだときの差を控える
    _move_cursor(x, y)
    time.sleep(CLICK_HOLD_SEC)
    left0, top0, _, _ = win32gui.GetWindowRect(hwnd)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(DRAG_PRESS_WAIT_SEC)
    cursor_x, cursor_y = win32api.GetCursorPos()
    offset0 = (left0 - cursor_x, top0 - cursor_y)

    # 2. 少しずつ動かし、待ってから窓の位置とカーソルを読む
    offsets: list[tuple[int, int]] = []
    step = DRAG_DISTANCE_PX / DRAG_STEPS
    for index in range(1, DRAG_STEPS + 1):
        _move_cursor(round(x + step * index), y)
        time.sleep(DRAG_STEP_WAIT_SEC)
        if index % DRAG_SAMPLE_EVERY == 0:
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
            cursor_x, cursor_y = win32api.GetCursorPos()
            offsets.append((left - cursor_x, top - cursor_y))

    # 3. 放して、動いた距離を読む
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(SETTLE_SEC)
    left1, top1, _, _ = win32gui.GetWindowRect(hwnd)
    deviation = max(
        max(abs(dx - offset0[0]), abs(dy - offset0[1])) for dx, dy in offsets
    )
    return DragResult(
        offset_at_press=offset0,
        offsets_while_moving=offsets,
        max_deviation_px=deviation,
        moved_px=(left1 - left0, top1 - top0),
    )


# === Qt のメインスレッドでの呼び出し ===


@dataclass
class _Job:
    """メインスレッドで動かす関数と、その結果か失敗。"""

    fn: Callable[[], Any]
    result: Any = None
    error: BaseException | None = None


class MainThreadCall(QObject):
    """ほかのスレッドから、Qt のメインスレッドで関数を動かして結果を待つ。メインスレッドで作る。"""

    request = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.request.connect(self._run, Qt.ConnectionType.BlockingQueuedConnection)

    def _run(self, job: _Job) -> None:
        """関数を動かし、結果か失敗を控える。"""
        try:
            job.result = job.fn()
        except BaseException as error:  # noqa: BLE001 呼び出し元のスレッドで出し直す
            job.error = error

    def __call__(self, fn: Callable[[], Any]) -> Any:
        """fn をメインスレッドで動かし、結果を返す。"""
        job = _Job(fn)
        self.request.emit(job)
        if job.error is not None:
            raise job.error
        return job.result


def _indicator() -> QWidget | None:
    """文字起こし中の表示（出ていれば）。"""
    for widget in QApplication.topLevelWidgets():
        if widget.objectName() == "transcribing_indicator" and widget.isVisible():
            return widget
    return None


@dataclass
class IndicatorGeometry:
    """文字起こし中の表示の、実機の画素での位置と、押す・つかむ場所。"""

    hwnd: int
    buttons: dict[str, tuple[int, int]]
    grab_point: tuple[int, int]


def _to_physical(widget: QWidget, point: QPoint, window: QWidget, hwnd: int) -> tuple[int, int]:
    """widget の中の点を、窓の実機の左上と画面の倍率で実機の画素へ移す。"""
    global_point = widget.mapToGlobal(point)
    ratio = window.screen().devicePixelRatio()
    left, top, _, _ = win32gui.GetWindowRect(hwnd)
    origin = window.frameGeometry().topLeft()
    return (
        round(left + (global_point.x() - origin.x()) * ratio),
        round(top + (global_point.y() - origin.y()) * ratio),
    )


def indicator_geometry() -> IndicatorGeometry | None:
    """文字起こし中の表示が出ていれば、そのハンドルと、各ボタンの中心・見出しの行のつかむ点を返す（メインスレッドで呼ぶ）。"""
    window = _indicator()
    if window is None:
        return None
    hwnd = int(window.winId())
    buttons = {
        button.objectName().removeprefix("switch_button_"): _to_physical(
            button, button.rect().center(), window, hwnd
        )
        for button in window.findChildren(SwitchButton)
    }
    head = window.findChild(HeadRow)
    grab = QPoint(round(head.width() * HEAD_ROW_GRAB_RATIO), head.height() // 2)
    return IndicatorGeometry(hwnd=hwnd, buttons=buttons, grab_point=_to_physical(head, grab, window, hwnd))


def checked_output() -> str | None:
    """選んだ状態の切り替えのボタンの出力先（メインスレッドで呼ぶ）。"""
    window = _indicator()
    if window is None:
        return None
    for button in window.findChildren(SwitchButton):
        if button.isChecked():
            return button.objectName().removeprefix("switch_button_")
    return None


@dataclass
class ButtonOverlap:
    """1 つのボタンの、名前の文字の範囲と右上の丸い印の範囲。"""

    output_id: str
    button_size: tuple[int, int]
    text_rect: tuple[int, int, int, int]
    badge_rect: tuple[int, int, int, int]
    overlaps: bool


def _text_rect(button: SwitchButton) -> QRect:
    """名前のラベルの中で文字が描かれる範囲を、ボタンの座標で返す。"""
    label = button.findChildren(QLabel)[0]
    metrics = label.fontMetrics()
    width = metrics.horizontalAdvance(label.text())
    height = metrics.height()
    geometry = label.geometry()
    alignment = label.alignment()
    # 横の揃え: 中央なら真ん中、右なら右端、それ以外は左端から描く
    if alignment & Qt.AlignmentFlag.AlignHCenter:
        x = geometry.x() + (geometry.width() - width) // 2
    elif alignment & Qt.AlignmentFlag.AlignRight:
        x = geometry.right() + 1 - width
    else:
        x = geometry.x()
    # 縦の揃え: QLabel の既定は上下の中央
    y = geometry.y() + (geometry.height() - height) // 2
    return QRect(x, y, width, height)


def button_overlaps() -> list[ButtonOverlap]:
    """全ての切り替えのボタンで、名前の文字の範囲と、選んだときに描く丸い印の範囲が重なるかを返す（メインスレッドで呼ぶ）。"""
    window = _indicator()
    if window is None:
        return []
    results: list[ButtonOverlap] = []
    for button in window.findChildren(SwitchButton):
        text = _text_rect(button)
        # 印の範囲は SwitchButton.paintEvent と同じ式
        badge = QRect(
            button.width() - CHECK_BADGE_SIZE_PX - CHECK_BADGE_MARGIN_PX,
            CHECK_BADGE_MARGIN_PX,
            CHECK_BADGE_SIZE_PX,
            CHECK_BADGE_SIZE_PX,
        )
        results.append(
            ButtonOverlap(
                output_id=button.objectName().removeprefix("switch_button_"),
                button_size=(button.width(), button.height()),
                text_rect=(text.x(), text.y(), text.width(), text.height()),
                badge_rect=(badge.x(), badge.y(), badge.width(), badge.height()),
                overlaps=text.intersects(badge),
            )
        )
    return results


def capture_indicator(path: Path) -> None:
    """文字起こし中の表示が出ている画面の範囲を、実機の画面から撮って保存する（メインスレッドで呼ぶ）。"""
    window = _indicator()
    if window is None:
        return
    geometry = window.frameGeometry()
    pixmap = window.screen().grabWindow(
        0, geometry.x(), geometry.y(), geometry.width(), geometry.height()
    )
    pixmap.save(str(path))


# === 常駐アプリの差し替え ===


class FakeHotkeyListener:
    """HotkeyListener の代わり。受付は始めず、登録された関数を控える。"""

    def __init__(self) -> None:
        self.bindings: dict[str, Callable[[], None]] = {}

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """登録されたホットキーと関数を控える。"""
        self.bindings = dict(bindings)

    def stop(self) -> None:
        """受付を始めていないため、何もしない。"""


@dataclass
class Spy:
    """差し替えで控えたもの。"""

    hotkeys: FakeHotkeyListener | None = None
    handlers: Any = None
    transcribed: list[str] = field(default_factory=list)


def install_spies(spy: Spy, wav_input: WavInput) -> None:
    """main() が作るホットキーの受付・録音の入力・システム音量・文字起こしを差し替え、配線を控える。"""
    volume = VolumeLog()
    session_deps = main_module.SessionDeps
    build_handlers = main_module.build_handlers

    def make_hotkey_listener() -> FakeHotkeyListener:
        """ホットキーの受付の代わりを作って控える。"""
        spy.hotkeys = FakeHotkeyListener()
        return spy.hotkeys

    def make_session_deps(**fields: Any) -> Any:
        """文字起こしの戻りを遅らせる包みをはさんで、本物の SessionDeps を作る。"""
        transcribe = fields["transcribe"]

        def slow_transcribe(*args: Any, **kwargs: Any) -> Any:
            """本物で起こし、戻りを TRANSCRIBE_DELAY_SEC 遅らせる。"""
            result = transcribe(*args, **kwargs)
            spy.transcribed.append(str(result))
            time.sleep(TRANSCRIBE_DELAY_SEC)
            return result

        return session_deps(**{**fields, "transcribe": slow_transcribe})

    def spy_build_handlers(*args: Any, **kwargs: Any) -> Any:
        """本物で配線し、配線を控える。"""
        spy.handlers = build_handlers(*args, **kwargs)
        return spy.handlers

    main_module.HotkeyListener = make_hotkey_listener  # type: ignore[assignment] 検証で差し替える
    main_module.SessionDeps = make_session_deps  # type: ignore[assignment]
    main_module.build_handlers = spy_build_handlers  # type: ignore[assignment]
    main_module.open_input = wav_input  # type: ignore[assignment]
    main_module.lower_volume = volume.lower  # type: ignore[assignment]
    main_module.restore_volume = volume.restore  # type: ignore[assignment]


# === 検証の 1 回 ===


@dataclass
class CaseResult:
    """切り替え先 1 つぶんの結果。"""

    show_hotkeys: bool
    initial_output: str
    target_output: str
    attempts: int = 0
    foreground_before_press: bool = False
    foreground_after_click: bool = False
    switched: bool = False
    foreground_after_drag: bool = False
    foreground_after_deliver: bool = False
    drag: dict[str, Any] | None = None
    buttons: list[dict[str, Any]] = field(default_factory=list)
    transcribed: str = ""
    notepad_text: str = ""
    notepad_all_texts: list[str] = field(default_factory=list)
    notepad_focus_before_press: str = ""
    notepad_focus_after_deliver: str = ""
    clipboard: str = ""
    screenshot: str = ""
    error: str = ""


MAX_ATTEMPTS = 3
"""押す前に前面がメモ帳の入力欄でなかった回をやり直す上限。"""


def _wait(condition: Callable[[], object], timeout_sec: float, what: str) -> None:
    """condition が真になるまで待つ。上限までに真にならなければ失敗にする。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(POLL_SEC)
    raise RuntimeError(f"{what}を待ちきれなかった")


def _hotkey_of(spy: Spy, output_id: str) -> str:
    """出力先の確定のホットキー。"""
    settings = spy.handlers.settings_store.get()
    return next(output.hotkey for output in settings.outputs if output.id == output_id)


def run_case(spy: Spy, call: MainThreadCall, result: CaseResult, wav_input: WavInput) -> None:
    """メモ帳を前面に置いたまま録音して確定し、文字起こし中に切り替えのボタンを押して見出しの行を動かし、届いた先を読む。"""
    manager = spy.handlers.session_manager
    bindings = spy.hotkeys.bindings
    stamp = datetime.now().strftime("%H%M%S")
    notepad = open_notepad(f"poc112_{result.target_output}_{int(result.show_hotkeys)}_{stamp}")
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result.attempts = attempt
            notepad.clear()
            pyperclip.copy(CLIPBOARD_SENTINEL)
            bring_to_front(notepad.hwnd)
            # 利用者と同じく入力欄をクリックして、入力欄にキーボードのフォーカスを置く
            left, top, right, bottom = win32gui.GetWindowRect(notepad.edit)
            click((left + right) // 2, (top + bottom) // 2)
            time.sleep(SETTLE_SEC)

            # 1. 録音を始め、WAV を流し終えたら、切り替え先と違う出力先で確定する（ホットキーの受付のスレッドと同じく、メインスレッドの外から呼ぶ）
            bindings[UNUSED_START_HOTKEY]()
            _wait(lambda: manager.current() is not None, UI_TIMEOUT_SEC, "録音の始まり")
            wav_input.wait_played_out()
            bindings[_hotkey_of(spy, result.initial_output)]()
            _wait(lambda: call(indicator_geometry) is not None, UI_TIMEOUT_SEC, "文字起こし中の表示")
            time.sleep(SETTLE_SEC)

            # 2. 押す前に前面がメモ帳でないか、入力欄にフォーカスが無ければ、届け終えるのを待ってやり直す
            result.foreground_before_press = foreground() == notepad.hwnd
            result.notepad_focus_before_press = notepad.focused_class()
            if result.foreground_before_press and result.notepad_focus_before_press == NOTEPAD_EDIT_CLASS:
                break
            _wait(lambda: call(indicator_geometry) is None, DELIVER_TIMEOUT_SEC, "届け終わり")
            time.sleep(AFTER_DELIVER_SEC)
        else:
            raise RuntimeError("押す前にメモ帳の入力欄が前面のフォーカスにならなかった")

        # 3. 切り替えのボタンを実物のマウスで押す
        geometry: IndicatorGeometry = call(indicator_geometry)
        click(*geometry.buttons[result.target_output])
        time.sleep(SETTLE_SEC)
        result.foreground_after_click = foreground() == notepad.hwnd
        _wait(lambda: call(checked_output) == result.target_output, UI_TIMEOUT_SEC, "切り替え")
        result.switched = True

        # 4. 選んだボタンの名前と印の範囲を求め、画面を撮る
        result.buttons = [asdict(overlap) for overlap in call(button_overlaps)]
        shot = RESULTS_DIR / f"{result.target_output}_hotkeys-{str(result.show_hotkeys).lower()}.png"
        call(lambda: capture_indicator(shot))
        result.screenshot = shot.name

        # 5. 見出しの行をつかんで動かす
        geometry = call(indicator_geometry)
        result.drag = asdict(drag(geometry.hwnd, *geometry.grab_point))
        result.foreground_after_drag = foreground() == notepad.hwnd

        # 6. 届け終えるのを待ち、前面・メモ帳の本文・クリップボードを読む
        _wait(lambda: call(indicator_geometry) is None, DELIVER_TIMEOUT_SEC, "届け終わり")
        time.sleep(AFTER_DELIVER_SEC)
        result.foreground_after_deliver = foreground() == notepad.hwnd
        result.notepad_text = notepad.text()
        result.notepad_all_texts = notepad.all_texts()
        result.notepad_focus_after_deliver = notepad.focused_class()
        result.clipboard = pyperclip.paste()
        result.transcribed = spy.transcribed[-1] if spy.transcribed else ""
    finally:
        notepad.close()


# === 起動 ===


def run_app(show_hotkeys: bool, cases: list[tuple[str, str]], wav_input: WavInput) -> list[CaseResult]:
    """`ui.transcribing_show_hotkeys` を show_hotkeys にした常駐アプリを実機の画面に出して起動し、cases（確定の出力先・切り替え先）を順に流す。"""
    data_dir = Path(tempfile.mkdtemp(prefix="poc112_"))
    extra = f"[ui]\ntranscribing_show_hotkeys = {str(show_hotkeys).lower()}\n"
    (data_dir / "settings.toml").write_text(settings_text(free_port(), extra), encoding="utf-8")
    spy = Spy()
    install_spies(spy, wav_input)
    results = [CaseResult(show_hotkeys, initial, target) for initial, target in cases]

    def exec_loop(application: QApplication) -> int:
        """メインスレッドの呼び出し口を作り、別のスレッドで検証を流して、イベントループを回す。"""
        call = MainThreadCall()

        def scenario() -> None:
            """起動を待ち、cases を流し、終わったらイベントループを抜ける。"""
            try:
                _wait(lambda: spy.hotkeys is not None and spy.hotkeys.bindings, STARTUP_TIMEOUT_SEC, "起動")
                for result in results:
                    try:
                        run_case(spy, call, result, wav_input)
                    except Exception as error:  # noqa: BLE001 1 回の失敗を控えて次の回へ進む
                        result.error = f"{type(error).__name__}: {error}"
            finally:
                call(application.quit)

        threading.Thread(target=scenario, daemon=True).start()
        return application.exec()

    original_clipboard = pyperclip.paste()
    try:
        main_module.main(["--data-dir", str(data_dir)], exec_loop=exec_loop)
    finally:
        pyperclip.copy(original_clipboard)
    return results


def main() -> None:
    """ホットキーを出す設定で 3 つの切り替え先を、出さない設定で 1 つを流し、結果を JSON に書く。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    samples = read_wav(synthesize_speech(SPEECH_TEXT, Path(tempfile.gettempdir()) / "poc112_speech.wav"))
    wav_input = WavInput(samples)
    results = run_app(
        True,
        [("copy_only", "paste_only"), ("paste_only", "copy_only"), ("copy_only", "paste_and_send")],
        wav_input,
    )
    results += run_app(False, [("paste_and_send", "paste_only")], wav_input)
    out = RESULTS_DIR / "results.json"
    out.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()