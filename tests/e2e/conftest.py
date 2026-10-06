"""E2E テストの共通フィクスチャ。実機のテストなので `--run-e2e` が無ければ skip する（ガードは tests/conftest.py）。"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pyperclip
import pytest

from tests.support.app_driver import IDLE, AppDriver
from tests.support.browser_target import BrowserTarget
from tests.support.desktop import PasteTarget, close_explorer, get_uia
from tests.support.fixtures import receiver, start_inprocess, start_service  # noqa: F401 フィクスチャとして使う
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
def browser_target() -> Iterator[BrowserTarget]:
    """ブラウザ添付のプリセットの開き先を 127.0.0.1 に立てる。Edge が無ければ skip する。テストの後に開いた窓を閉じて止める。"""
    from voice_paste.integrations.browser.opener import EDGE_COMMAND, EDGE_PATHS

    if shutil.which(EDGE_COMMAND) is None and not any(Path(path).exists() for path in EDGE_PATHS):
        pytest.skip("Microsoft Edge が見つからない（ブラウザ添付はアプリのウィンドウとして Edge で開く）")
    target = BrowserTarget()
    target.start()
    yield target
    target.close_window()
    target.stop()


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

    def _start(
        extra_settings: str = "",
        *,
        wait_idle: bool = True,
        port: int | None = None,
        wait_for_api: bool = True,
        prepare: Callable[[Path], None] | None = None,
    ) -> AppDriver:
        """設定を足して起動し、待機中を待つ。prepare は起動の前に置き場所へファイルを用意する関数。"""
        # タスクバーで読めても、隠れたアイコンの一覧の中のアイコンを読み落とさない
        others = get_uia().tray_tooltips(include_hidden=True)
        if others:
            pytest.skip(
                "ほかの voice-paste（普段使いの旧版など）のトレイのアイコンが出ている（今のヒント: "
                f"{', '.join(others)}）。ホットキーを両方が受け、この常駐アプリのアイコンと見分けにくいため、終了してから実行する"
            )
        service = start_service(
            extra_settings,
            accept_injected_hotkeys=True,
            port=port,
            wait_for_api=wait_for_api,
            prepare=prepare,
        )
        driver = AppDriver(service)
        drivers.append(driver)
        if wait_idle:
            driver.wait_tray_state(IDLE)
        return driver

    yield _start
    for driver in drivers:
        AppDriver.kill_service_processes_for(driver.service.data_dir)
