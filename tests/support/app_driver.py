"""実機の常駐アプリ（`python -m voice_paste --data-dir {一時フォルダ}`）を、画面・トレイから操作・観測する。

画面設計の項目 ID（objectName）で部品を引き、UI Automation で操作する。録音は、合成したキーでホットキーを押して始める。
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from tests.support.desktop import (
    COM_ERRORS,
    ProcessInfo,
    Uia,
    _elements,
    descendants,
    get_uia,
    kill_tree,
    press_hotkey,
    processes_with,
    wait_until,
)
from tests.support.real_service import RealService

SERVICE_COMMAND = "-m voice_paste"
"""常駐アプリのコマンドラインに含まれる言葉（venv の python.exe は本体のプロセスを子に持つ）。"""

WORKER_COMMAND = "voice_paste.integrations.whisper.worker"
"""文字起こしワーカーのコマンドラインに含まれるモジュール名。"""

START_HOTKEY = "<ctrl>+<alt>+d"
"""既定の録音開始のホットキー。"""

PAUSE_HOTKEY = "<ctrl>+<alt>+z"
CANCEL_HOTKEY = "<ctrl>+<alt>+q"
"""既定の一時停止・取り消しのホットキー。"""

STATE_NAMES = ("準備中", "待機中", "録音中", "文字起こし中", "失敗")
"""トレイのヒントの状態の名前（画面設計「トレイ」）。"""

IDLE = "待機中"
RECORDING = "録音中"
TRANSCRIBING = "文字起こし中"
"""トレイのヒントの状態の名前。"""

STATE_TIMEOUT_SEC = 120.0
"""状態が変わるのを待つ上限（文字起こしを含む）。"""

WINDOW_TIMEOUT_SEC = 20.0
EXIT_TIMEOUT_SEC = 30.0
TRAY_POSITION_TOLERANCE_PX = 4
"""トレイのアイコンの位置が同じとみなす差。"""


class AppDriver:
    """起動した常駐アプリの画面・トレイを操作・観測する。"""

    def __init__(
        self,
        service: RealService,
        uia: Uia | None = None,
        *,
        baseline_tooltips: list[str] | None = None,
    ) -> None:
        """起動した常駐アプリを受ける。baseline_tooltips は起動する前のトレイのアイコンのヒント（空でなければ、その分を除いて状態を読む）。"""
        self.service = service
        self.uia = uia or get_uia()
        self._baseline = Counter(baseline_tooltips or [])
        self._pids: list[int] = []
        self._tray_center: tuple[int, int] | None = None
        """この常駐アプリのトレイのアイコンの中心（普段使いの旧版のアイコンと見分けるため、メニューを開いて確かめた位置を覚える）。"""

    # --- プロセス ---

    @property
    def pids(self) -> list[int]:
        """画面を持つプロセスの番号（venv の python.exe の本体と、そのランチャー）。"""
        if not self._pids:
            found = processes_with(SERVICE_COMMAND, self.service.process.pid)
            self._pids = [p.pid for p in found if WORKER_COMMAND not in p.command_line]
        return self._pids

    def worker_processes(self) -> list[ProcessInfo]:
        """文字起こしワーカーのプロセス（ランチャーと本体）を返す。"""
        return processes_with(WORKER_COMMAND, self.service.process.pid)

    def kill_workers(self) -> int:
        """文字起こしワーカーを止め、止めたワーカーの数（ランチャーの数）を返す。"""
        workers = self.worker_processes()
        worker_pids = {w.pid for w in workers}
        # ランチャー（親がワーカーでないもの）を子孫ごと止める
        roots = [w for w in workers if w.parent_pid not in worker_pids]
        for root in roots:
            kill_tree(root.pid)
        return len(roots)

    def log_messages(self, level: str | None = None) -> list[str]:
        """常駐アプリのログの文（msg）を、level（無ければ全て）で絞って並べる。"""
        return [
            str(record["msg"])
            for record in self.service.log_records()
            if level is None or record["level"] == level
        ]

    def notified(self, event: str) -> bool:
        """ユーザーへの知らせ（notify）のログに、event（transcription_failed など）が書かれているか。"""
        return any(f"ユーザーへの知らせ（{event}" in message for message in self.log_messages())

    def service_descendant_pids(self) -> set[int]:
        """起動したプロセスの子孫（本体・ワーカーを含む）の番号。"""
        return {p.pid for p in descendants(self.service.process.pid)}

    # --- トレイ ---

    @staticmethod
    def _near(first: tuple[int, int], second: tuple[int, int]) -> bool:
        """2 つの座標がほぼ同じか。"""
        return abs(first[0] - second[0]) <= TRAY_POSITION_TOLERANCE_PX and (
            abs(first[1] - second[1]) <= TRAY_POSITION_TOLERANCE_PX
        )

    def own_tray_icon(self) -> Any | None:
        """この常駐アプリのトレイのアイコンを返す（無ければ None）。

        ヒントが同じ形の旧版のアイコンが並ぶことがあるため、初めに右クリックでメニューを開き、
        この常駐アプリのメニュー（menu_start）が出るアイコンを選んで、その位置を覚える。
        """
        buttons = self.uia.tray_icon_buttons()
        if self._tray_center is not None:
            for button in buttons:
                if self._near(self.uia.center(button), self._tray_center):
                    return button
            return None
        for button in buttons:
            self.uia.click_center(button, right=True)
            if wait_until(lambda: self.uia.find(self.pids, "menu_start") is not None, 3.0):
                self._tray_center = self.uia.center(button)
                self.close_menu()
                return button
            self.close_menu()
        return None

    def _own_tooltips(self) -> list[str]:
        """今のトレイのアイコンのヒントから、起動する前からあったもの（旧版のアイコン）を除き、この常駐アプリの状態の名前だけを並べる。"""
        current = Counter(self.uia.tray_tooltips())
        remaining = current - self._baseline
        return [name for name in remaining.elements() if name in STATE_NAMES]

    def tray_icon_gone(self) -> bool:
        """この常駐アプリのトレイのアイコンが消えているか。"""
        return not self._own_tooltips()

    def tray_state(self) -> str | None:
        """トレイのアイコンのヒントの状態の名前（待機中・録音中など）。アイコンが無ければ None。"""
        names = self._own_tooltips()
        return names[0] if names else None

    def wait_tray_state(self, state: str, timeout_sec: float = STATE_TIMEOUT_SEC) -> None:
        """トレイのアイコンが state になるのを待つ。ならなければテストを失敗させる。"""
        assert wait_until(lambda: self.tray_state() == state, timeout_sec), (
            f"トレイが {state} にならなかった（今は {self.tray_state()}）"
        )

    def open_tray_menu(self) -> None:
        """トレイのアイコンを右クリックしてメニューを開く。"""
        icon = self.own_tray_icon()
        assert icon is not None, "この常駐アプリのトレイのアイコンが見つからない"
        self.uia.click_center(icon, right=True)
        self.uia.wait_find(self.pids, "menu_start", WINDOW_TIMEOUT_SEC)

    def click_tray_icon(self) -> None:
        """トレイのアイコンを左クリックする（既定の操作）。"""
        icon = self.own_tray_icon()
        assert icon is not None, "この常駐アプリのトレイのアイコンが見つからない"
        self.uia.click_center(icon)

    def choose_tray_menu(self, item: str) -> None:
        """トレイのメニューを開いて、項目 ID（menu_start など）の項目を選ぶ。"""
        self.open_tray_menu()
        element = self.uia.wait_find(self.pids, item, WINDOW_TIMEOUT_SEC)
        self.uia.click_center(element)

    def menu_item_enabled(self, item: str) -> bool:
        """トレイのメニューを開いて、項目が押せるかを返し、メニューを閉じる。"""
        self.open_tray_menu()
        element = self.uia.wait_find(self.pids, item, WINDOW_TIMEOUT_SEC)
        enabled = bool(element.CurrentIsEnabled)
        self.close_menu()
        return enabled

    def close_menu(self) -> None:
        """開いているメニューを Esc で閉じる。"""
        from tests.support.desktop import type_keys

        type_keys("<esc>")
        time.sleep(0.3)

    # --- 録音 ---

    def start_recording(self) -> None:
        """録音開始のホットキーを押して録音を始める。"""
        press_hotkey(START_HOTKEY)

    def window(self, name: str) -> Any | None:
        """画面（recording_window・transcribing_indicator・settings_window・busy_dialog）の部品を引く。"""
        return self.uia.find(self.pids, name)

    def wait_window(self, name: str, timeout_sec: float = WINDOW_TIMEOUT_SEC) -> Any:
        """画面が出るのを待つ。"""
        return self.uia.wait_find(self.pids, name, timeout_sec)

    def wait_window_gone(self, name: str, timeout_sec: float = WINDOW_TIMEOUT_SEC) -> bool:
        """画面が消えるのを待ち、消えたかを返す。"""
        return self.uia.wait_gone(self.pids, name, timeout_sec)

    def press(self, name: str) -> None:
        """項目 ID のボタン（pause_button・output_button_paste_and_send など）を押す。"""
        self.uia.invoke(self.uia.wait_find(self.pids, name, WINDOW_TIMEOUT_SEC))

    def texts(self, name: str) -> list[str]:
        """項目 ID の部品の表示の文字を並べる。"""
        return self.uia.texts(self.uia.wait_find(self.pids, name, WINDOW_TIMEOUT_SEC))

    def press_in(self, container: str, name: str) -> None:
        """確認ダイアログ（reset_dialog・discard_dialog）の中のボタンを押す（窓にも同じ項目 ID のボタンがあるため）。"""
        dialog = self.wait_window(container)
        holder: list[Any] = []

        def _found() -> bool:
            element = self.uia.find_in(dialog, name)
            if element is not None:
                holder.append(element)
            return element is not None

        assert wait_until(_found, WINDOW_TIMEOUT_SEC), f"{container} の {name} が見つからない"
        self.uia.invoke(holder[-1])

    def label(self, name: str) -> str:
        """項目 ID のラベルの文字（名前）を返す。"""
        return str(self.uia.wait_find(self.pids, name, WINDOW_TIMEOUT_SEC).CurrentName)

    def recording_rect(self) -> tuple[int, int, int, int]:
        """録音の画面の矩形（左・上・右・下。物理ピクセル）を返す。"""
        return self.uia.rect(self.wait_window("recording_window"))

    def recording_hwnd(self) -> int:
        """録音の画面のウィンドウハンドルを返す。"""
        return int(self.wait_window("recording_window").CurrentNativeWindowHandle)

    # --- 設定画面 ---

    def open_settings(self) -> None:
        """トレイの「設定…」から設定画面を開く。"""
        self.choose_tray_menu("menu_settings")
        self.wait_window("settings_window")

    def select_group(self, name: str) -> None:
        """設定画面のまとまりのメニューから、まとまりを選ぶ。"""
        window = self.wait_window("settings_window")
        found = window.FindAll(self.uia.client.TreeScope_Descendants, self.uia._true)
        for element in _elements(found):
            try:
                is_item = element.CurrentAutomationId.endswith(".group_menu") and element.CurrentName == name
            except COM_ERRORS:
                continue
            if is_item:
                # リストの項目は UI Automation の選択では現在の行が変わらないため、マウスでクリックする
                self.uia.click_center(element)
                return
        raise AssertionError(f"まとまり {name} が見つからない")

    def set_field(self, key: str, text: str) -> None:
        """設定画面の文字の欄（field_{キー}）に文字を入れる。"""
        self.set_text(f"field_{key}", text)

    def set_text(self, name: str, text: str) -> None:
        """項目 ID の文字の欄（preset_title_0 など）に文字を入れる。"""
        element = self.uia.wait_find(self.pids, name, WINDOW_TIMEOUT_SEC)
        self.uia.set_value(element, text)

    def field_value(self, key: str) -> str:
        """設定画面の文字の欄の今の文字を返す。"""
        return self.uia.value(self.uia.wait_find(self.pids, f"field_{key}", WINDOW_TIMEOUT_SEC))

    # --- 終了・再起動 ---

    def wait_exit(self, timeout_sec: float = EXIT_TIMEOUT_SEC) -> bool:
        """起動したプロセスが終わるのを待ち、終わったかを返す。"""
        return wait_until(lambda: not self.service.is_running(), timeout_sec)

    @staticmethod
    def service_processes_for(data_dir: Path) -> list[ProcessInfo]:
        """data_dir で動いている常駐アプリのプロセス（再起動で起動し直したものを含む）を返す。"""
        from tests.support.desktop import process_table

        return [
            p
            for p in process_table()
            if SERVICE_COMMAND in p.command_line
            and str(data_dir) in p.command_line
            and WORKER_COMMAND not in p.command_line
        ]

    @staticmethod
    def kill_service_processes_for(data_dir: Path) -> None:
        """data_dir で動いている常駐アプリ（再起動で起動し直したものを含む）を全て止める。"""
        for process in AppDriver.service_processes_for(data_dir):
            kill_tree(process.pid)
