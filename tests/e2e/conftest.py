"""E2E テストの共通フィクスチャ。実機のテストなので `--run-e2e` が無ければ skip する（ガードは tests/conftest.py）。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pyperclip
import pytest

from tests.support.app_driver import IDLE, AppDriver
from tests.support.desktop import PasteTarget, close_explorer, get_uia
from tests.support.fixtures import receiver, start_service  # noqa: F401 フィクスチャとして使う
from tests.support.real_service import RealService

CLIPBOARD_SENTINEL = "voice-paste-e2e-clipboard-sentinel"
"""録音の前にクリップボードへ置く目印の文字。"""


@pytest.fixture
def clipboard_sentinel() -> Iterator[str]:
    """クリップボードに目印を置き、テストの後に元の中身へ戻す。目印を返す。"""
    original = pyperclip.paste()
    pyperclip.copy(CLIPBOARD_SENTINEL)
    yield CLIPBOARD_SENTINEL
    pyperclip.copy(original)


@pytest.fixture
def paste_target(tmp_path: Path) -> Iterator[PasteTarget]:
    """貼り付け先（別プロセスの入力欄）を出して前面に置く。テストの後に閉じる。"""
    target = PasteTarget(tmp_path / "paste_target.json")
    yield target
    target.close()


@pytest.fixture
def explorer_to_close() -> Iterator[list[Path]]:
    """テストで開いたフォルダのエクスプローラーを、テストの後に閉じる。開いたフォルダのパスを入れて使う。"""
    folders: list[Path] = []
    yield folders
    for folder in folders:
        close_explorer(folder)


@pytest.fixture
def start_app(start_service: Callable[..., RealService]) -> Iterator[Callable[..., AppDriver]]:  # noqa: F811
    """本物の常駐アプリを起動し、トレイが待機中になるまで待って、画面・トレイを操作する AppDriver を返す関数を返す。

    再起動で起動し直したプロセスも、テストの後に止める。
    """
    drivers: list[AppDriver] = []

    def _start(extra_settings: str = "", *, wait_idle: bool = True) -> AppDriver:
        """設定を足して起動し、待機中を待つ。"""
        others = get_uia().tray_tooltips()
        if others:
            pytest.skip(
                "ほかの voice-paste（普段使いの旧版など）のトレイのアイコンが出ている（ヒント: "
                f"{', '.join(others)}）。同じ実行ファイルのアイコンは 1 つのボタンにまとまり、この常駐アプリのメニューを開けないため、終了してから実行する"
            )
        driver = AppDriver(start_service(extra_settings))
        drivers.append(driver)
        if wait_idle:
            driver.wait_tray_state(IDLE)
        return driver

    yield _start
    for driver in drivers:
        AppDriver.kill_service_processes_for(driver.service.data_dir)
