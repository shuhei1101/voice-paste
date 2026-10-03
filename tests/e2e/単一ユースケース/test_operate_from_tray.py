"""単一ユースケース「トレイから操作する」の E2E テスト。

本物の常駐アプリを起動し、トレイのアイコンを右クリックしてメニューの項目を選ぶ（UI Automation でアイコン・項目を引き、
マウスでクリックする）。エクスプローラーに開くフォルダは、起動した一時フォルダ（`--data-dir`）の下。
`--run-e2e` が無ければ skip する。

あわせて、reviewer の指摘（#21）から次の 2 つを実機で確かめる。
- 設定画面で欄を変えたまま開いている間に、トレイの「終了」・Ctrl+Break で終えたとき、確かめのダイアログで止まらず終わるか
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.support.app_driver import AppDriver
from tests.support.desktop import explorer_locations, wait_until

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

OPEN_TIMEOUT_SEC = 20.0
"""エクスプローラーが開くのを待つ上限。"""

RESTART_TIMEOUT_SEC = 180.0
"""再起動した新しい常駐アプリが待ち受けを始めるまで待つ上限。"""

EXIT_LIMIT_SEC = 20.0
"""終わらせてから、確かめのダイアログで止まらずに終わるまで待つ上限。"""


def _token(data_dir: Path) -> str | None:
    """起動ごとのトークンのファイルから、トークンを読む（無ければ None）。"""
    try:
        return str(json.loads((data_dir / "api_token").read_text(encoding="utf-8"))["token"])
    except (OSError, ValueError, KeyError):
        return None


def test_normal_when_open_log_folder(start_app: StartApp, explorer_to_close: list[Path]) -> None:
    """「ログフォルダを開く」を選ぶと、エクスプローラーでログの置き場所が開く（正常シナリオ）。"""
    # 準備
    app = start_app()
    log_dir = app.service.data_dir / "log"
    explorer_to_close.append(log_dir)

    # 実行
    app.choose_tray_menu("menu_open_log_folder")

    # 検証
    assert wait_until(lambda: log_dir in explorer_locations(), OPEN_TIMEOUT_SEC)


def test_normal_when_open_settings_folder(start_app: StartApp, explorer_to_close: list[Path]) -> None:
    """「設定フォルダを開く」を選ぶと、エクスプローラーで settings.toml のあるフォルダが開く（正常シナリオ）。"""
    # 準備
    app = start_app()
    settings_dir = app.service.data_dir
    explorer_to_close.append(settings_dir)

    # 実行
    app.choose_tray_menu("menu_open_settings_folder")

    # 検証
    assert wait_until(lambda: settings_dir in explorer_locations(), OPEN_TIMEOUT_SEC)


def test_normal_when_restart(start_app: StartApp) -> None:
    """「再起動」を選ぶと、前のプロセスが終わり、新しい常駐アプリが待機中になる（正常シナリオ）。"""
    # 準備
    app = start_app()
    data_dir = app.service.data_dir
    old_token = _token(data_dir)

    # 実行
    app.choose_tray_menu("menu_restart")

    # 検証
    assert app.wait_exit(), "前のプロセスが終わらなかった"
    assert wait_until(lambda: _token(data_dir) not in (None, old_token), RESTART_TIMEOUT_SEC), (
        "新しい常駐アプリが待ち受けを始めなかった"
    )
    assert wait_until(lambda: app.tray_state() == "待機中", RESTART_TIMEOUT_SEC)
    assert AppDriver.service_processes_for(data_dir) != []


def test_normal_when_quit(start_app: StartApp) -> None:
    """「終了」を選ぶと、トレイのアイコンが消え、常駐アプリとワーカーが終わり、API が応えなくなる（正常シナリオ）。"""
    # 準備
    app = start_app()
    assert app.worker_processes() != []

    # 実行
    app.choose_tray_menu("menu_quit")

    # 検証
    assert app.wait_exit(), "常駐アプリが終わらなかった"
    assert app.service.process.returncode == 0
    assert wait_until(app.tray_icon_gone, OPEN_TIMEOUT_SEC)
    assert wait_until(lambda: app.worker_processes() == [], OPEN_TIMEOUT_SEC)
    with pytest.raises(httpx.ConnectError):
        app.service.http.post("/sessions", json={"callback_url": "http://127.0.0.1:9/"})


# === 設定画面で欄を変えたまま終える（#21 の reviewer の指摘: 実機で確かめる） ===


def _open_settings_with_change(app: AppDriver) -> None:
    """設定画面を開いて欄を書き換える（保存しない）。"""
    app.open_settings()
    app.select_group("録音")
    app.set_field("recording.fade_sec", "2.5")


def test_exit_when_settings_changed_by_tray_quit(start_app: StartApp) -> None:
    """設定画面で欄を変えたまま開いている間にトレイの「終了」を選んでも、確かめのダイアログで止まらず終わる。"""
    # 準備
    app = start_app()
    _open_settings_with_change(app)

    # 実行
    app.choose_tray_menu("menu_quit")

    # 検証
    stopped = app.wait_exit(EXIT_LIMIT_SEC)
    assert stopped, (
        "終了が止まった（変えた値を捨てる確認のダイアログが出ていないか: "
        f"{app.window('discard_dialog') is not None}）"
    )


def test_exit_when_settings_changed_by_ctrl_break(start_app: StartApp) -> None:
    """設定画面で欄を変えたまま開いている間に Ctrl+Break で終えても、確かめのダイアログで止まらず終わる。"""
    # 準備
    app = start_app()
    _open_settings_with_change(app)

    # 実行
    started = time.monotonic()
    exit_code = app.service.shutdown()

    # 検証
    assert time.monotonic() - started < EXIT_LIMIT_SEC, "終わるまでに時間がかかった（確かめのダイアログで止まっていないか）"
    assert exit_code == 0
