"""実機の Windows のデスクトップを操作・観測する補助（実機の E2E が使う）。

- 画面・トレイ・メニュー・通知は UI Automation（comtypes）で引く。Qt の部品の AutomationId は
  `QApplication.{親の objectName}….{objectName}` の形で、画面設計の項目 ID が末尾に出る
- ボタン・欄・チェックボックスは UI Automation のパターン（Invoke・Value・Toggle・SelectionItem）で操作し、
  トレイのアイコンの右クリックとメニューの選択だけマウスで行う
- 録音開始のホットキーは、合成したキー（SendInput）で押す。常駐アプリは環境変数 `VOICE_PASTE_ACCEPT_INJECTED_HOTKEYS=1` で起動し、
  合成したキーもホットキーとして受ける
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# UI Automation の座標・マウスの座標・ウィンドウの座標を同じ物理ピクセルにそろえる（拡大率のあるモニターで位置がずれないように）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    pass

import comtypes.client  # noqa: E402
import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402
from pynput import keyboard  # noqa: E402

NO_MICROPHONE_ENV = "VOICE_PASTE_E2E_NO_MICROPHONE"
"""録音の入力の音声デバイスを外した環境で実行するときに `1` を指定する環境変数。"""

POLL_SEC = 0.1
UI_TIMEOUT_SEC = 20.0
"""画面・メニューが出る・消えるのを待つ上限。"""

AUTOMATION_CLSID = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
HIDDEN_ICONS_BUTTON_NAMES = ("非表示のアイコンを表示する", "隠れているインジケーターを表示する", "Show Hidden Icons")
"""隠れたアイコンの一覧を開くボタンの名前（Windows の版・言語ごと）。"""

CLOSE_POPUP_HOTKEY = "<esc>"
"""開いたポップアップ（隠れたアイコンの一覧）を閉じるキー。"""

TRAY_TOOLTIP_PREFIX = "voice-paste:"
"""トレイのアイコンのヒントの先頭（`voice-paste: 待機中` など）。"""

PAUSE_AFTER_CLICK_SEC = 0.3
POWERSHELL_TIMEOUT_SEC = 30.0
MOUSE_SETTLE_SEC = 0.05
KEY_SETTLE_SEC = 0.05
DRAG_STEPS = 20
"""ドラッグで、始点から終点まで分けて動かす回数。"""


def wait_until(condition: Callable[[], Any], timeout_sec: float = UI_TIMEOUT_SEC) -> bool:
    """condition が真になるか timeout_sec が過ぎるまで待ち、真になったかを返す。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(POLL_SEC)
    return bool(condition())


# === プロセス ===


@dataclass(frozen=True)
class ProcessInfo:
    """プロセスの 1 行（番号・親・コマンドライン）。"""

    pid: int
    parent_pid: int
    command_line: str


def process_table() -> list[ProcessInfo]:
    """全てのプロセスを PowerShell（Get-CimInstance）で引く。"""
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(  # noqa: S603 固定のコマンド
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=POWERSHELL_TIMEOUT_SEC,
        check=True,
    )
    rows = json.loads(result.stdout)
    return [
        ProcessInfo(int(row["ProcessId"]), int(row["ParentProcessId"]), row["CommandLine"] or "")
        for row in rows
    ]


def descendants(root_pid: int, table: Iterable[ProcessInfo] | None = None) -> list[ProcessInfo]:
    """root_pid とその子孫のプロセスを返す（venv の python.exe は本体のプロセスを子に持つため、子孫まで辿る）。"""
    rows = list(table) if table is not None else process_table()
    found = {root_pid}
    result: list[ProcessInfo] = []
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row.pid in found and row not in result:
                result.append(row)
            if row.parent_pid in found and row.pid not in found:
                found.add(row.pid)
                changed = True
    return result


def kill_tree(pid: int) -> None:
    """プロセスと子孫を止める。"""
    subprocess.run(  # noqa: S603 固定のコマンド
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False
    )


def processes_with(command_fragment: str, tree_root_pid: int) -> list[ProcessInfo]:
    """tree_root_pid の子孫のうち、コマンドラインに command_fragment を含むプロセスを返す。"""
    return [p for p in descendants(tree_root_pid) if command_fragment in p.command_line]


# === UI Automation ===


COM_ERRORS = (comtypes.COMError, ValueError)
"""UI Automation の部品が消えた・読めないときに出る例外（探している間に窓が閉じることがあるため、読めない部品は無いものとして扱う）。"""


def _automation_id(element: Any) -> str:
    """部品の AutomationId（読めなければ空）。"""
    try:
        return str(element.CurrentAutomationId)
    except COM_ERRORS:
        return ""


def _elements(array: Any) -> list[Any]:
    """UI Automation の部品の配列を、読める部品だけの list にする（読んでいる間に消えた部品は除く）。"""
    result: list[Any] = []
    for index in range(array.Length):
        try:
            result.append(array.GetElement(index))
        except COM_ERRORS:
            continue
    return result


class Uia:
    """UI Automation のクライアント。画面の部品は項目 ID（objectName）で引く。"""

    def __init__(self) -> None:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as client

        self.client = client
        self.automation = comtypes.client.CreateObject(
            AUTOMATION_CLSID, interface=client.IUIAutomation
        )
        self._true = self.automation.CreateTrueCondition()

    # --- 引く ---

    def top_windows(self, pids: Iterable[int]) -> list[Any]:
        """デスクトップの直下の窓（メニューのポップアップを含む）のうち、pids のプロセスの出ているものを返す。

        窓は Win32 の列挙（EnumWindows）で素早く引き、UI Automation の部品にする（ほかのアプリの窓の部品は読まない）。
        """
        wanted = set(pids)
        handles: list[int] = []

        def _collect(handle: int, _extra: object) -> None:
            """出ている窓のうち、pids のプロセスのものを控える。"""
            if win32gui.IsWindowVisible(handle):
                _thread, process_id = win32process.GetWindowThreadProcessId(handle)
                if process_id in wanted:
                    handles.append(handle)

        win32gui.EnumWindows(_collect, None)
        result: list[Any] = []
        for handle in handles:
            try:
                result.append(self.automation.ElementFromHandle(handle))
            except COM_ERRORS:
                continue
        return result

    def find(self, pids: Iterable[int], object_name: str) -> Any | None:
        """pids のプロセスの窓の中から、項目 ID（objectName）の部品を引く。無ければ None。"""
        suffix = f".{object_name}"
        for window in self.top_windows(pids):
            try:
                if _automation_id(window).endswith(suffix):
                    return window
                found = window.FindAll(self.client.TreeScope_Descendants, self._true)
                for element in _elements(found):
                    if _automation_id(element).endswith(suffix):
                        return element
            except COM_ERRORS:
                continue
        return None

    def find_in(self, container: Any, object_name: str) -> Any | None:
        """部品（確認ダイアログなど）の子孫から、項目 ID の部品を引く。同じ項目 ID が窓とダイアログにあるときに使う。"""
        suffix = f".{object_name}"
        try:
            found = container.FindAll(self.client.TreeScope_Descendants, self._true)
            for element in _elements(found):
                if _automation_id(element).endswith(suffix):
                    return element
        except COM_ERRORS:
            return None
        return None

    def wait_find(
        self, pids: Iterable[int], object_name: str, timeout_sec: float = UI_TIMEOUT_SEC
    ) -> Any:
        """項目 ID の部品が出るのを待って返す。出なければテストを失敗させる。"""
        pid_list = list(pids)
        holder: list[Any] = []

        def _found() -> bool:
            element = self.find(pid_list, object_name)
            if element is not None:
                holder.append(element)
            return element is not None

        assert wait_until(_found, timeout_sec), f"{object_name} が出なかった"
        return holder[-1]

    def wait_gone(
        self, pids: Iterable[int], object_name: str, timeout_sec: float = UI_TIMEOUT_SEC
    ) -> bool:
        """項目 ID の部品が消えるのを待ち、消えたかを返す。"""
        pid_list = list(pids)
        return wait_until(lambda: self.find(pid_list, object_name) is None, timeout_sec)

    def texts(self, element: Any) -> list[str]:
        """部品とその子孫の名前（表示の文字）を、空でないものだけ並べる。"""
        names = [element.CurrentName]
        found = element.FindAll(self.client.TreeScope_Descendants, self._true)
        for child in _elements(found):
            try:
                names.append(child.CurrentName)
            except COM_ERRORS:
                continue
        return [name for name in names if name]

    @staticmethod
    def rect(element: Any) -> tuple[int, int, int, int]:
        """部品の矩形（左・上・右・下。物理ピクセル）を返す。"""
        rect = element.CurrentBoundingRectangle
        return rect.left, rect.top, rect.right, rect.bottom

    # --- 操作する ---

    def invoke(self, element: Any) -> None:
        """ボタン・メニューの項目を押す（Invoke パターン）。"""
        pattern = element.GetCurrentPattern(self.client.UIA_InvokePatternId)
        pattern.QueryInterface(self.client.IUIAutomationInvokePattern).Invoke()
        time.sleep(PAUSE_AFTER_CLICK_SEC)

    def set_value(self, element: Any, text: str) -> None:
        """文字の欄に文字を入れる（Value パターン）。"""
        pattern = element.GetCurrentPattern(self.client.UIA_ValuePatternId)
        pattern.QueryInterface(self.client.IUIAutomationValuePattern).SetValue(text)
        time.sleep(PAUSE_AFTER_CLICK_SEC)

    def value(self, element: Any) -> str:
        """文字の欄の今の文字を返す。"""
        pattern = element.GetCurrentPattern(self.client.UIA_ValuePatternId)
        return str(pattern.QueryInterface(self.client.IUIAutomationValuePattern).CurrentValue)

    def select(self, element: Any) -> None:
        """リストの項目・ラジオボタンを選ぶ（SelectionItem パターン）。"""
        pattern = element.GetCurrentPattern(self.client.UIA_SelectionItemPatternId)
        pattern.QueryInterface(self.client.IUIAutomationSelectionItemPattern).Select()
        time.sleep(PAUSE_AFTER_CLICK_SEC)

    def focus(self, element: Any) -> None:
        """部品へキーボードのフォーカスを移す。"""
        element.SetFocus()
        time.sleep(PAUSE_AFTER_CLICK_SEC)

    def has_focus(self, element: Any) -> bool:
        """部品がキーボードのフォーカスを持っているか。"""
        return bool(element.CurrentHasKeyboardFocus)

    def click_center(self, element: Any, *, right: bool = False) -> None:
        """部品の中心をマウスでクリックする（トレイのアイコン・メニューの項目）。"""
        left, top, right_edge, bottom = self.rect(element)
        click((left + right_edge) // 2, (top + bottom) // 2, right=right)

    def find_by_name(self, text: str, *, timeout_sec: float = UI_TIMEOUT_SEC) -> Any | None:
        """デスクトップ全体から、名前に text を含む部品を探す（通知センターの通知など、別のプロセスの部品用）。"""
        condition = self.automation.CreatePropertyConditionEx(
            self.client.UIA_NamePropertyId,
            text,
            self.client.PropertyConditionFlags_MatchSubstring,
        )
        holder: list[Any] = []

        def _found() -> bool:
            element = self.automation.GetRootElement().FindFirst(
                self.client.TreeScope_Descendants, condition
            )
            # 見つからなければ comtypes は None でなく空のポインタを返す（真偽は偽）
            if element:
                holder.append(element)
            return bool(element)

        return holder[-1] if wait_until(_found, timeout_sec) else None

    # --- トレイ ---

    def tray_tooltips(self, *, include_hidden: bool = False) -> list[str]:
        """トレイのアイコンのヒントの今の状態の名前を、アイコンごとに 1 つ並べる（`voice-paste: 待機中` なら `待機中`）。

        まずタスクバーのボタンから読む。読めなければ隠れたアイコンの一覧を開いて、一覧の中のボタンから読む。
        include_hidden が真のときは、タスクバーで読めても一覧を開いて読み、両方の今の状態を並べる。
        普段使いの旧版の常駐アプリのアイコンのヒントも並ぶ。
        """
        if not include_hidden:
            tooltips = self._tooltips_of(self._tray_buttons())
            if tooltips:
                return tooltips
        # 一覧を開いている間は、タスクバーのボタンも同じ探し方で読める
        return self._hidden_tray_tooltips() or self._tooltips_of(self._tray_buttons())

    def tray_icon_buttons(self) -> list[Any]:
        """トレイのアイコンのボタン（名前が `voice-paste:` で始まるもの）を並べる。

        タスクバーに出ていなければ、隠れたアイコンの一覧（オーバーフロー）を開いて探す。
        """
        icons = self._icons()
        if icons:
            return icons
        chevron = self._hidden_icons_button()
        if chevron is None:
            return []
        self.click_center(chevron)
        time.sleep(PAUSE_AFTER_CLICK_SEC * 2)
        return self._icons()

    def _hidden_tray_tooltips(self) -> list[str]:
        """隠れたアイコンの一覧を開いてヒントの状態を読み、読んだ後は一覧を閉じて開く前の前面のウィンドウへ戻す。"""
        chevron = self._hidden_icons_button()
        if chevron is None:
            # 隠れたアイコンの一覧を開くボタンが無い: 読めるヒントは無い
            return []
        previous = foreground_hwnd()
        self.invoke(chevron)
        time.sleep(PAUSE_AFTER_CLICK_SEC)
        try:
            return self._tooltips_of(self._tray_buttons())
        finally:
            # 一覧が前面に出ているときだけ Escape で閉じる（出ていなければ、ほかのウィンドウへ Escape を送らない）
            if foreground_hwnd() != previous:
                type_keys(CLOSE_POPUP_HOTKEY)
                time.sleep(PAUSE_AFTER_CLICK_SEC)
            # 閉じても前面が戻らないときは、開く前の前面のウィンドウを前面に戻す
            if foreground_hwnd() != previous and win32gui.IsWindow(previous):
                force_foreground(previous)

    def _hidden_icons_button(self) -> Any | None:
        """隠れたアイコンの一覧を開くボタンを返す（無ければ None）。"""
        for name in HIDDEN_ICONS_BUTTON_NAMES:
            condition = self.automation.CreatePropertyConditionEx(
                self.client.UIA_NamePropertyId,
                name,
                self.client.PropertyConditionFlags_MatchSubstring,
            )
            button = self.automation.GetRootElement().FindFirst(
                self.client.TreeScope_Descendants, condition
            )
            # 見つからなければ comtypes は None でなく空のポインタを返す（真偽は偽）
            if button:
                return button
        return None

    @staticmethod
    def _tooltips_of(buttons: Iterable[Any]) -> list[str]:
        """トレイのボタンの名前から、アイコンごとの今の状態の名前（名前の最後のヒント）を並べる。

        Windows はボタンの名前に、アイコンを出した時点のヒントと今のヒントを並べる（`voice-paste: 準備中 voice-paste: 待機中`）。
        """
        tooltips: list[str] = []
        for button in buttons:
            current = str(button.CurrentName).split(TRAY_TOOLTIP_PREFIX)[-1].strip()
            if current:
                tooltips.append(current)
        return tooltips

    def _icons(self) -> list[Any]:
        """名前が `voice-paste:` で始まる、アイコン 1 つ分のボタンを並べる（名前に並ぶヒントの数では絞らない）。"""
        return [
            button
            for button in self._tray_buttons()
            if str(button.CurrentName).strip().startswith(TRAY_TOOLTIP_PREFIX)
        ]

    def _tray_buttons(self) -> list[Any]:
        """名前に `voice-paste:` を含むボタンを、デスクトップ全体から全て探す。"""
        name = self.automation.CreatePropertyConditionEx(
            self.client.UIA_NamePropertyId,
            TRAY_TOOLTIP_PREFIX,
            self.client.PropertyConditionFlags_MatchSubstring,
        )
        button = self.automation.CreatePropertyCondition(
            self.client.UIA_ControlTypePropertyId, self.client.UIA_ButtonControlTypeId
        )
        both = self.automation.CreateAndCondition(name, button)
        found = self.automation.GetRootElement().FindAll(self.client.TreeScope_Descendants, both)
        return _elements(found)

    @staticmethod
    def center(element: Any) -> tuple[int, int]:
        """部品の中心の座標。"""
        left, top, right, bottom = Uia.rect(element)
        return (left + right) // 2, (top + bottom) // 2


@dataclass
class _UiaHolder:
    """UI Automation のクライアントを 1 つだけ作って使い回す。"""

    instance: Uia | None = None


_HOLDER = _UiaHolder()


def get_uia() -> Uia:
    """UI Automation のクライアントを返す（初めて呼ぶときに作る）。"""
    if _HOLDER.instance is None:
        _HOLDER.instance = Uia()
    return _HOLDER.instance


# === マウス・キー ===


def click(x: int, y: int, *, right: bool = False) -> None:
    """画面の座標（物理ピクセル）をマウスでクリックする。"""
    win32api.SetCursorPos((x, y))
    time.sleep(MOUSE_SETTLE_SEC)
    down, up = (
        (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP)
        if right
        else (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP)
    )
    win32api.mouse_event(down, 0, 0, 0, 0)
    time.sleep(MOUSE_SETTLE_SEC)
    win32api.mouse_event(up, 0, 0, 0, 0)
    time.sleep(PAUSE_AFTER_CLICK_SEC)


def move_cursor(x: int, y: int) -> None:
    """マウスのカーソルを動かす。"""
    win32api.SetCursorPos((x, y))
    time.sleep(MOUSE_SETTLE_SEC)


def drag(start: tuple[int, int], end: tuple[int, int]) -> None:
    """マウスの左ボタンを start で押し、end まで少しずつ動かして放す（窓のドラッグ）。座標は物理ピクセル。"""
    win32api.SetCursorPos(start)
    time.sleep(MOUSE_SETTLE_SEC)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(MOUSE_SETTLE_SEC)
    for step in range(1, DRAG_STEPS + 1):
        x = start[0] + (end[0] - start[0]) * step // DRAG_STEPS
        y = start[1] + (end[1] - start[1]) * step // DRAG_STEPS
        win32api.SetCursorPos((x, y))
        time.sleep(MOUSE_SETTLE_SEC)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(PAUSE_AFTER_CLICK_SEC)


def type_keys(hotkey: str) -> None:
    """合成したキー（SendInput）で、pynput の書式のキーの組み合わせを押す。"""
    controller = keyboard.Controller()
    keys = keyboard.HotKey.parse(hotkey)
    for key in keys:
        controller.press(key)
        time.sleep(KEY_SETTLE_SEC)
    for key in reversed(keys):
        controller.release(key)
        time.sleep(KEY_SETTLE_SEC)


def open_notification_center() -> None:
    """通知センターを開く（Windows 11 は Win+N、Windows 10 は Win+A）。"""
    type_keys("<cmd>+n")
    time.sleep(PAUSE_AFTER_CLICK_SEC * 3)


def press_hotkey(hotkey: str) -> None:
    """常駐アプリのホットキー（pynput の書式）を、合成したキーで押す（常駐アプリは合成したキーを受ける起動にしてある）。"""
    type_keys(hotkey)
    time.sleep(PAUSE_AFTER_CLICK_SEC)


# === ウィンドウ・モニター・エクスプローラー ===


def z_order(hwnd: int) -> int:
    """最前面からの重なりの順（0 が最前面）。見つからなければ大きな値を返す。"""
    order: list[int] = []
    win32gui.EnumWindows(lambda handle, _extra: order.append(handle), None)
    return order.index(hwnd) if hwnd in order else len(order)


def force_foreground(hwnd: int) -> None:
    """ウィンドウを前面に出す（Alt を押して前面への切り替えの制限を外してから出す）。"""
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(PAUSE_AFTER_CLICK_SEC)


def foreground_hwnd() -> int:
    """今の前面のウィンドウのハンドルを返す。"""
    return int(win32gui.GetForegroundWindow())


def foreground_title() -> str:
    """今の前面のウィンドウの題を返す。"""
    return str(win32gui.GetWindowText(win32gui.GetForegroundWindow()))


@dataclass(frozen=True)
class Monitor:
    """接続しているモニター。"""

    work: tuple[int, int, int, int]
    """作業領域（左・上・右・下。物理ピクセル）。"""

    primary: bool
    """主のモニターか。"""

    def contains(self, rect: tuple[int, int, int, int]) -> bool:
        """矩形（左・上・右・下）が作業領域に収まっているか。"""
        left, top, right, bottom = self.work
        return rect[0] >= left and rect[1] >= top and rect[2] <= right and rect[3] <= bottom

    def center(self) -> tuple[int, int]:
        """作業領域の中心の座標。"""
        left, top, right, bottom = self.work
        return (left + right) // 2, (top + bottom) // 2


def monitors() -> list[Monitor]:
    """接続しているモニターを並べる。"""
    result: list[Monitor] = []
    for handle, _dc, _rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        result.append(Monitor(tuple(info["Work"]), bool(info["Flags"] & 1)))  # type: ignore[arg-type]
    return result


def explorer_locations() -> list[Path]:
    """開いているエクスプローラーのフォルダを並べる。"""
    import win32com.client

    shell = win32com.client.Dispatch("Shell.Application")
    locations: list[Path] = []
    for window in shell.Windows():
        url = str(getattr(window, "LocationURL", "") or "")
        if url.startswith("file:///"):
            locations.append(Path(urllib.parse.unquote(url[len("file:///"):])))
    return locations


def close_explorer(folder: Path) -> None:
    """folder を開いているエクスプローラーを閉じる。"""
    import win32com.client

    shell = win32com.client.Dispatch("Shell.Application")
    for window in shell.Windows():
        url = str(getattr(window, "LocationURL", "") or "")
        if url.startswith("file:///") and Path(urllib.parse.unquote(url[len("file:///"):])) == folder:
            window.Quit()


# === 音量・クリップボード・音声 ===


def master_volume() -> float:
    """既定の再生デバイスのマスター音量（0.0〜1.0）を読む。"""
    comtypes.CoInitialize()
    try:
        from pycaw.pycaw import AudioUtilities

        return float(AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar())
    finally:
        comtypes.CoUninitialize()


def speak(text: str) -> None:
    """Windows の音声合成（SAPI）で、スピーカーから text を読み上げる（読み終わるまで待つ）。マイクがその音を拾う前提。"""
    import win32com.client

    win32com.client.Dispatch("SAPI.SpVoice").Speak(text)


# === 貼り付け先 ===


PASTE_TARGET_TITLE = "voice-paste E2E paste target"
"""貼り付け先の窓の題。"""

PASTE_TARGET_SCRIPT = Path(__file__).with_name("paste_target.py")


class PasteTarget:
    """貼り付け先（別プロセスの入力欄）。入力欄の中身と Enter の回数を、ファイルへ書き出す。"""

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self.process = subprocess.Popen(  # noqa: S603 自分のインタープリタでテスト用のスクリプトを起動する
            [sys.executable, str(PASTE_TARGET_SCRIPT), str(state_file), PASTE_TARGET_TITLE]
        )
        assert wait_until(lambda: self._hwnd() != 0, UI_TIMEOUT_SEC), "貼り付け先の窓が出なかった"
        self.focus()

    def _hwnd(self) -> int:
        """貼り付け先の窓のハンドルを返す（無ければ 0）。"""
        return int(win32gui.FindWindow(None, PASTE_TARGET_TITLE))

    def focus(self) -> None:
        """貼り付け先を前面に出して入力欄にフォーカスを置く。"""
        force_foreground(self._hwnd())

    def hwnd(self) -> int:
        """貼り付け先の窓のハンドルを返す。"""
        return self._hwnd()

    def _state(self) -> dict[str, Any]:
        """書き出された入力欄の状態を読む（まだ無ければ空）。"""
        if not self.state_file.exists():
            return {"text": "", "enters": 0}
        try:
            return dict(json.loads(self.state_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return {"text": "", "enters": 0}

    def text(self) -> str:
        """入力欄の中身。"""
        return str(self._state()["text"])

    def enters(self) -> int:
        """入力欄で受けた Enter の回数。"""
        return int(self._state()["enters"])

    def close(self) -> None:
        """貼り付け先を閉じる。"""
        self.process.kill()
        self.process.wait()
