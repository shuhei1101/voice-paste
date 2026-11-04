"""単一ユースケース「トレイから操作する」の E2E テスト。

常駐アプリを pytest のプロセスの中で `main()` から起動し、トレイのメニューの項目の `QAction` を trigger して選ぶ。
実機のマウス・キーボードは使わず、Windows のシェル（タスクバーのトレイ・通知・エクスプローラー）は読まない。
フォルダが開いたことは、開く呼び出しを差し替えて渡されたパスで確かめる（開くフォルダは、起動した一時フォルダ `--data-dir` の下）。
終了・再起動は `main()` が戻ったことと戻り値で確かめ、再起動で起動し直す新しいプロセスだけは別プロセスで動き（Qt は offscreen）、
ログとトークンのファイルで確かめる。`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.integration.helpers import wait_until
from tests.support.instances import started_count
from tests.support.real_service import read_token_file
from tests.support.resident_app import ResidentApp, service_processes_for

pytestmark = pytest.mark.real_machine

RunApp = Callable[..., ResidentApp]

RESTARTED_TIMEOUT_SEC = 180.0
"""再起動した新しい常駐アプリが待ち受けを始めるまで待つ上限。"""

WORKERS_GONE_TIMEOUT_SEC = 20.0
"""常駐アプリが終わってから、文字起こしワーカーが終わるまで待つ上限。"""


def _token(data_dir: Path) -> object:
    """起動ごとのトークンのファイルから、トークンを読む（まだ無ければ None）。"""
    info = read_token_file(data_dir)
    return None if info is None else info["token"]


def _settings_bytes(data_dir: Path) -> bytes | None:
    """settings.yaml の中身を読む（まだ無ければ None）。"""
    try:
        return (data_dir / "settings.yaml").read_bytes()
    except OSError:
        return None


def _assert_restarted(app: ResidentApp, old_token: object) -> None:
    """前のプロセスと文字起こしワーカーが終わり、新しい常駐アプリが待機中になった（ログとトークンのファイル）ことを確かめる。"""
    assert app.exited_by_itself, "前のプロセスが終わらなかった"
    assert app.exit_code == 0
    assert wait_until(lambda: app.remaining_workers() == [], WORKERS_GONE_TIMEOUT_SEC), (
        "前の文字起こしワーカーが残っている"
    )
    assert wait_until(lambda: _token(app.data_dir) not in (None, old_token), RESTARTED_TIMEOUT_SEC), (
        "新しい常駐アプリが待ち受けを始めなかった"
    )
    assert wait_until(lambda: started_count(app.data_dir) == 2, RESTARTED_TIMEOUT_SEC)
    assert service_processes_for(app.data_dir) != []


def test_normal_when_open_log_folder(run_app: RunApp) -> None:
    """「ログフォルダを開く」を選ぶと、ログの置き場所を開く（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """メニューの項目を選び、開くはずのフォルダを確かめる。"""
        # 実行
        app.choose_tray_menu("menu_open_log_folder")

        # 検証
        assert app.opened_folders == [app.data_dir / "log"]

    run_app(case)


def test_normal_when_open_settings_folder(run_app: RunApp) -> None:
    """「設定フォルダを開く」を選ぶと、settings.yaml のあるフォルダを開く（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """メニューの項目を選び、開くはずのフォルダを確かめる。"""
        # 実行
        app.choose_tray_menu("menu_open_settings_folder")

        # 検証
        assert app.opened_folders == [app.data_dir]

    run_app(case)


def test_normal_when_restart(run_app: RunApp) -> None:
    """「再起動」を選ぶと、前のプロセスが終わり、新しい常駐アプリが待機中になる（正常シナリオ）。"""
    old_tokens: list[object] = []

    def case(app: ResidentApp) -> None:
        """メニューの「再起動」を選ぶ。"""
        # 準備
        old_tokens.append(_token(app.data_dir))

        # 実行
        app.choose_tray_menu("menu_restart")

    # 準備・実行: 常駐アプリが自分で抜けるのを待つ
    app = run_app(case, expect_exit=True)

    # 検証
    _assert_restarted(app, old_tokens[0])


def test_normal_when_quit(run_app: RunApp) -> None:
    """「終了」を選ぶと、トレイのアイコンが消え、常駐アプリとワーカーが終わり、API が応えなくなる（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """メニューの「終了」を選ぶ。"""
        # 準備
        assert app.worker_pids() != set()
        assert app.tray_visible()

        # 実行
        app.choose_tray_menu("menu_quit")

    # 準備・実行: 常駐アプリが自分で抜けるのを待つ
    app = run_app(case, expect_exit=True)

    # 検証
    assert app.exited_by_itself, "常駐アプリが終わらなかった"
    assert app.exit_code == 0
    assert not app.tray_visible()
    assert wait_until(lambda: app.remaining_workers() == [], WORKERS_GONE_TIMEOUT_SEC)
    with pytest.raises(httpx.ConnectError):
        app.post("/sessions", json_body={"callback_url": "http://127.0.0.1:9/"})


# === 設定画面で値を変えたまま終える ===


def _quit_by_tray_menu(app: ResidentApp) -> None:
    """トレイの「終了」を選ぶ。"""
    app.choose_tray_menu("menu_quit")


def _quit_by_ctrl_break(app: ResidentApp) -> None:
    """自分のプロセスの中で Ctrl+Break（SIGBREAK）を上げる。"""
    signal.raise_signal(signal.SIGBREAK)


def _change_settings_field(app: ResidentApp) -> None:
    """設定画面を開いて、保存せずに欄の値を変える。"""
    app.open_settings()
    app.select_group("出力先")
    app.set_field("outputs[0].enter_delay_sec", "2.5")


@pytest.mark.parametrize(
    "quit_app",
    [
        pytest.param(_quit_by_tray_menu, id="tray_quit"),
        pytest.param(
            _quit_by_ctrl_break,
            id="ctrl_break",
            marks=pytest.mark.skipif(
                not hasattr(signal, "SIGBREAK"), reason="SIGBREAK は Windows にだけある"
            ),
        ),
    ],
)
def test_normal_when_quit_with_unsaved_settings(
    run_app: RunApp, quit_app: Callable[[ResidentApp], None]
) -> None:
    """設定画面で値を変えたまま開いている間にトレイの「終了」・Ctrl+Break で終えても、変えた値を捨てる確認で止まらず終わり、終了コードは 0（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """設定画面で値を変えたまま、終える。"""
        # 準備
        _change_settings_field(app)

        # 実行
        quit_app(app)

    # 準備・実行: 常駐アプリが自分で抜けるのを待つ
    app = run_app(case, expect_exit=True)

    # 検証
    assert app.unexpected_dialogs == [], "変えた値を捨てる確認のダイアログが出た"
    assert app.exited_by_itself, "確かめのダイアログで止まったか、常駐アプリが終わらなかった"
    assert app.exit_code == 0


def test_normal_when_restart_with_unsaved_settings(run_app: RunApp) -> None:
    """設定画面で値を変えたままトレイの「再起動」を選んでも、変えた値を捨てる確認で止まらず前のプロセスが終わり、新しい常駐アプリが待機中になる。変えた値は保存されない（正常シナリオ）。"""
    old_tokens: list[object] = []
    settings_before: list[bytes | None] = []

    def case(app: ResidentApp) -> None:
        """設定画面で値を変えたまま、「再起動」を選ぶ。"""
        # 準備
        settings_before.append(_settings_bytes(app.data_dir))
        old_tokens.append(_token(app.data_dir))
        _change_settings_field(app)

        # 実行
        app.choose_tray_menu("menu_restart")

    # 準備・実行: 常駐アプリが自分で抜けるのを待つ
    app = run_app(case, expect_exit=True)

    # 検証
    assert app.unexpected_dialogs == [], "変えた値を捨てる確認のダイアログが出た"
    _assert_restarted(app, old_tokens[0])
    assert _settings_bytes(app.data_dir) == settings_before[0], (
        "設定画面で変えた値が settings.yaml に保存された"
    )
