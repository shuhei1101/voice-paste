"""単一ユースケース「常駐アプリを起動する」の E2E テスト。

本物の常駐アプリ（`python -m voice_paste --data-dir {一時フォルダ}`）を起動し、トレイ・API・ログ・履歴を観測する。
実機のマイクを開く録音は始めない（`--run-e2e` が無ければ skip する）。
前提は E2E テストの節のとおり（普段使いの voice-paste のトレイが出ていれば skip する）。

保持期間を過ぎた履歴とログの、常駐中の定期の削除（非機能要件の削除の間隔 24 時間ごと）は、待てないため確かめない。
起動時の削除だけを確かめる。
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.support.app_driver import IDLE, WINDOW_TIMEOUT_SEC, AppDriver
from tests.support.desktop import open_notification_center, type_keys, wait_until
from tests.support.instances import service_root_count, wait_for_takeover
from tests.support.real_service import LOOPBACK, RealService, spawn_process

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

FAILED = "失敗"
"""トレイのヒントの、起動に失敗した状態の名前。"""

NO_SUCH_MODEL_SETTINGS = '[transcription.local_whisper]\nmodel = "voice-paste-e2e-no-such-model"\n'
"""ローカルの Whisper のモデルに存在しない名前を設定する（文字起こしワーカーがモデルを読み込めずに error を返す）。"""

RETENTION_ONE_DAY_SETTINGS = "[history]\nretention_days = 1\n\n[logging]\nretention_days = 1\n"
"""履歴とログの保持期間を 1 日にする設定。"""

ENGINE_FAILURE_TITLE = "起動に失敗しました"
"""文字起こしのエンジンを準備できないときの通知の見出し。"""

API_FAILURE_TITLE = "API を使えません"
"""API の待ち受けを始められないときの通知の見出し。"""

NO_RECORDING_WAIT_SEC = 2.0
"""ホットキーを押してから、録音が始まっていないことを確かめるために待つ秒数。"""

TOAST_SETTLE_SEC = 8.0
"""通知が畳まれて通知センターに残るのを待つ秒数。"""

PREVIOUS_EXIT_TIMEOUT_SEC = 30.0
"""後から起動した後、前のプロセスが終わるまで待つ上限。"""

AI_CHAT_URL = "https://chatgpt.com/"
"""古い AI チャットの設定の送り先に書く URL（開かない）。"""


def _old_ai_chat_settings() -> str:
    """古い AI チャットの設定（送り先 2 つ。うち 1 つは出さない）を書いた settings.toml の続きを返す。"""
    return (
        '[[outputs]]\nid = "paste_and_send"\n\n'
        '[[outputs]]\nid = "ai_chat"\n\n'
        f'[[outputs.targets]]\nname = "ChatGPT"\nurl = "{AI_CHAT_URL}"\n'
        'hotkey = "<ctrl>+<alt>+1"\nenabled = true\n\n'
        '[[outputs.targets]]\nname = "Claude"\nurl = "https://claude.ai/new"\n'
        'hotkey = "<ctrl>+<alt>+3"\nenabled = false\n'
    )


def _prepare_expired_files(data_dir: Path) -> tuple[date, date]:
    """起動の前に、2 日前の日付と今日の日付の履歴とログを置く。2 日前の日付と今日の日付を返す。"""
    today = date.today()
    expired = today - timedelta(days=2)
    for day in (expired, today):
        history_day = data_dir / "history" / day.strftime("%Y%m%d")
        history_day.mkdir(parents=True)
        (history_day / f"{day.strftime('%Y%m%d')}120000_old.wav").write_bytes(b"RIFF")
        (history_day / f"{day.strftime('%Y%m%d')}120000_old.txt").write_text(
            "古い履歴", encoding="utf-8"
        )
        (data_dir / "log").mkdir(exist_ok=True)
        (data_dir / "log" / f"{day.isoformat()}.log").write_text("古いログ\n", encoding="utf-8")
    return expired, today


def _notification_in_center(app: AppDriver, title: str) -> bool:
    """通知が畳まれて通知センターに残るのを待ち、通知センターに title の通知があるかを返して、通知センターを閉じる。"""
    time.sleep(TOAST_SETTLE_SEC)
    open_notification_center()
    notification = app.uia.find_by_name(title, timeout_sec=WINDOW_TIMEOUT_SEC)
    type_keys("<esc>")
    return notification is not None


@pytest.fixture
def occupied_port() -> Iterator[int]:
    """127.0.0.1 の空きポートを、ほかのプロセスが先に使っている状態にして、そのポートを返す。"""
    with socket.socket() as occupier:
        occupier.bind((LOOPBACK, 0))
        occupier.listen()
        yield int(occupier.getsockname()[1])


def test_normal(start_app: StartApp) -> None:
    """ショートカットから起動すると、トレイが待機中になり、API がトークンに応え、ワーカーが動く（正常シナリオ）。"""
    # 準備・実行: 起動し、トレイが待機中になるまで待つ
    app = start_app()
    service = app.service

    # 検証
    assert app.tray_state() == IDLE
    assert (service.data_dir / "api_token").exists()
    # トークンのファイルから読んだ今回のトークンには応え、合わないトークン・トークン無しは断る
    assert service.post("/sessions/unknown/stop").status_code == 404
    assert service.post("/sessions/unknown/stop", authorized=False).status_code == 401
    assert (
        service.post(
            "/sessions/unknown/stop", headers={"Authorization": "Bearer previous-start-token"}
        ).status_code
        == 401
    )
    assert app.worker_processes() != []


def test_normal_when_previous_running(start_app: StartApp) -> None:
    """常駐中にもう一度起動すると、前の常駐サービスが終わり、新しい常駐サービスが待機中で出て、プロセスが 1 つだけになる（正常シナリオ）。"""
    # 準備: 前の常駐サービスを起動する
    previous = start_app()
    data_dir = previous.service.data_dir

    # 実行: 同じ置き場所でもう 1 つ起動し、入れ替わって立ち上がるまで待つ
    second_process = spawn_process(
        data_dir, accept_injected_hotkeys=True, stdout_name="stdout_second.log"
    )
    wait_for_takeover(data_dir, second_process)
    current = AppDriver(RealService.attach(data_dir, second_process))
    current.wait_tray_state(IDLE)

    # 検証: 前のプロセスが終わり、トレイに前のアイコンが残らず待機中のアイコンが 1 つだけで、プロセスが 1 つだけ
    assert previous.wait_exit(PREVIOUS_EXIT_TIMEOUT_SEC), "前の常駐サービスが終わらなかった"
    assert previous.service.process.returncode == 0
    assert [name for name in current.uia.tray_tooltips() if name == IDLE] == [IDLE]
    assert current.tray_state() == IDLE
    assert service_root_count(data_dir) == 1


def test_normal_when_expired_history_and_logs(start_app: StartApp) -> None:
    """保持期間を過ぎた日付の履歴とログは起動時に消え、今日の日付のものは残る（正常シナリオ）。"""
    # 準備: 保持期間を 1 日にし、2 日前と今日の日付の履歴とログを置いて起動する
    dates: list[tuple[date, date]] = []

    def _prepare(data_dir: Path) -> None:
        """起動の前に、2 日前と今日の履歴とログを置く。"""
        dates.append(_prepare_expired_files(data_dir))

    app = start_app(RETENTION_ONE_DAY_SETTINGS, prepare=_prepare)
    data_dir = app.service.data_dir
    expired, today = dates[0]

    # 検証
    assert not (data_dir / "history" / expired.strftime("%Y%m%d")).exists()
    assert not (data_dir / "log" / f"{expired.isoformat()}.log").exists()
    assert (data_dir / "history" / today.strftime("%Y%m%d")).is_dir()
    assert len(list((data_dir / "history" / today.strftime("%Y%m%d")).iterdir())) == 2
    today_log = data_dir / "log" / f"{today.isoformat()}.log"
    assert today_log.read_text(encoding="utf-8").startswith("古いログ\n")


def test_error_when_engine_unavailable(start_app: StartApp) -> None:
    """文字起こしのエンジンを準備できなければ、トレイで起動の失敗が知らされ、ログに理由が書かれ、設定を開けて、録音は始まらない（異常シナリオ）。"""
    # 準備・実行: 存在しないモデルの名前で起動する（トークンのファイルは書かれない）
    app = start_app(NO_SUCH_MODEL_SETTINGS, wait_idle=False, wait_for_api=False)
    app.wait_tray_state(FAILED)

    # 検証: 失敗の通知とログ、プロセスは終わらずトレイのメニューから設定を開ける
    assert _notification_in_center(app, ENGINE_FAILURE_TITLE), "通知センターに起動の失敗の通知が無い"
    assert any(message.startswith("起動に失敗した（") for message in app.log_messages("ERROR"))
    assert app.service.is_running()
    assert app.menu_item_enabled("menu_settings")
    # 録音開始のホットキーを押しても録音が始まらない
    app.start_recording()
    time.sleep(NO_RECORDING_WAIT_SEC)
    assert app.tray_state() == FAILED
    assert app.window("recording_window") is None
    assert not (app.service.data_dir / "api_token").exists()


def test_error_when_api_unavailable(start_app: StartApp, occupied_port: int) -> None:
    """API の待ち受けを始められなければ、トレイで知らされ、ログに理由が書かれる（異常シナリオ）。"""
    # 準備・実行: API のポートをほかのプロセスが使っている状態で起動する（トークンのファイルは書かれない）
    app = start_app(port=occupied_port, wait_for_api=False)

    # 検証
    assert wait_until(lambda: app.notified("api_unavailable"), WINDOW_TIMEOUT_SEC)
    assert _notification_in_center(app, API_FAILURE_TITLE), "通知センターに API を使えない通知が無い"
    assert any(
        message.startswith("API の待ち受けを始められなかった（") for message in app.log_messages("ERROR")
    )
    assert not (app.service.data_dir / "api_token").exists()


def test_normal_when_old_ai_chat_settings_remain(start_app: StartApp) -> None:
    """古い AI チャットの設定が残った settings.toml でも起動でき、settings.toml は書き換わらない（正常シナリオ）。"""
    # 準備・実行: 古い設定で起動し、トレイが待機中になるまで待つ
    extra_settings = _old_ai_chat_settings()
    app = start_app(extra_settings)

    # 検証: 起動が止まらず、settings.toml が書き換わっていない
    assert app.tray_state() == IDLE
    settings_file = app.service.data_dir / "settings.toml"
    assert settings_file.read_text(encoding="utf-8") == (
        f"[api]\nport = {app.service.port}\n\n{extra_settings}\n"
    )
