"""単一ユースケース「トレイから操作する」の E2E テスト。

本物の常駐アプリを起動し、トレイのアイコンを右クリックしてメニューの項目を選ぶ（UI Automation でアイコン・項目を引き、
マウスでクリックする）。エクスプローラーに開くフォルダは、起動した一時フォルダ（`--data-dir`）の下。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import json
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


def _settings_bytes(data_dir: Path) -> bytes | None:
    """settings.toml の中身を読む（まだ無ければ None）。"""
    try:
        return (data_dir / "settings.toml").read_bytes()
    except OSError:
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


# === 設定画面で値を変えたまま終える ===


def _quit_by_tray_menu(app: AppDriver) -> int | None:
    """トレイの「終了」を選び、プロセスが終わったときの終了コードを返す（終わらなければ None）。"""
    app.choose_tray_menu("menu_quit")
    return app.service.process.returncode if app.wait_exit(EXIT_LIMIT_SEC) else None


def _quit_by_ctrl_break(app: AppDriver) -> int | None:
    """起動したコンソールへ Ctrl+Break を送り、プロセスが終わったときの終了コードを返す（終わらなければ None）。"""
    exit_code = app.service.shutdown()
    return exit_code if not app.service.is_running() else None


@pytest.mark.parametrize(
    "quit_app",
    [
        pytest.param(_quit_by_tray_menu, id="tray_quit"),
        pytest.param(_quit_by_ctrl_break, id="ctrl_break"),
    ],
)
def test_normal_when_quit_with_unsaved_settings(
    start_app: StartApp, quit_app: Callable[[AppDriver], int | None]
) -> None:
    """設定画面で値を変えたまま開いている間にトレイの「終了」・Ctrl+Break で終えても、変えた値を捨てる確認で止まらず終わり、終了コードは 0（正常シナリオ）。"""
    # 準備
    app = start_app()
    app.open_settings()
    app.select_group("録音")
    app.set_field("recording.fade_sec", "2.5")

    # 実行
    exit_code = quit_app(app)

    # 検証
    assert exit_code == 0, (
        "確かめのダイアログで止まったか、終了コードが 0 でない（変えた値を捨てる確認のダイアログが出ていないか: "
        f"{app.window('discard_dialog') is not None}）"
    )


def test_normal_when_restart_with_unsaved_settings(start_app: StartApp) -> None:
    """設定画面で値を変えたままトレイの「再起動」を選んでも、変えた値を捨てる確認で止まらず前のプロセスが終わり、新しい常駐アプリが待機中になる。変えた値は保存されない（正常シナリオ）。"""
    # 準備
    app = start_app()
    data_dir = app.service.data_dir
    settings_before = _settings_bytes(data_dir)
    old_token = _token(data_dir)
    app.open_settings()
    app.select_group("録音")
    app.set_field("recording.fade_sec", "2.5")

    # 実行
    app.choose_tray_menu("menu_restart")

    # 検証
    assert app.wait_exit(EXIT_LIMIT_SEC), (
        "確かめのダイアログで止まって前のプロセスが終わらなかった（変えた値を捨てる確認のダイアログが出ていないか: "
        f"{app.window('discard_dialog') is not None}）"
    )
    assert wait_until(lambda: _token(data_dir) not in (None, old_token), RESTART_TIMEOUT_SEC), (
        "新しい常駐アプリが待ち受けを始めなかった"
    )
    assert wait_until(lambda: app.tray_state() == "待機中", RESTART_TIMEOUT_SEC)
    assert _settings_bytes(data_dir) == settings_before, "設定画面で変えた値が settings.toml に保存された"
