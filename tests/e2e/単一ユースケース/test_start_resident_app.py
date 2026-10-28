"""単一ユースケース「常駐アプリを起動する」の E2E テスト。

常駐アプリを pytest のプロセスの中で `main()` から起動し（`--data-dir` の一時フォルダ、Qt は offscreen）、
トレイのヒント・API・ログ・履歴を観測する。実機のマウス・キーボードは使わない。
録音を始めるケースは、録音の入力を WAV を流すものに、システム音量を呼ばれた値を控えるものに差し替え、実機のマイクを開かず、システム音量を変えない。
古い AI チャットの設定が残っているケースは、さらに貼り付けのキーを送信したキーを控えるものに、ブラウザを開く呼び出しを渡された URL を控えるものに差し替える。
「前の常駐サービスが動いている」だけは、別プロセスで 2 つ起動して、ログ・トークンのファイル・プロセスで確かめる
（`--run-e2e` が無ければ skip する）。

保持期間を過ぎた履歴とログの、常駐中の定期の削除（非機能要件の削除の間隔 24 時間ごと）は、待てないため確かめない。
起動時の削除だけを確かめる。
"""

from __future__ import annotations

import importlib.util
import socket
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import httpx
import pyperclip
import pytest
from PySide6.QtWidgets import QWidget

from tests.integration.helpers import wait_until
from tests.support.inprocess import (
    SPEECH_TEXT,
    SPEECH_WORD,
    KeyLog,
    encode_audio,
    silence_input,
    speech_input,
    synthesize_speech,
)
from tests.support.instances import service_root_count, wait_for_takeover
from tests.support.openai_endpoint import API_KEY
from tests.support.real_service import (
    LOOPBACK,
    UNUSED_START_HOTKEY,
    RealService,
    read_log_records,
    settings_text,
    spawn_process,
)
from tests.support.resident_app import (
    CANCEL_HOTKEY,
    FAILED,
    IDLE,
    RECORDING,
    UI_TIMEOUT_SEC,
    ResidentApp,
)
from voice_paste.integrations.openai.credentials import OPENAI_API_KEY_ENV
from voice_paste.ui.windows.settings_window import format_hotkey

pytestmark = pytest.mark.real_machine

RunApp = Callable[..., ResidentApp]

NO_SUCH_MODEL_SETTINGS = '[transcription.local_whisper]\nmodel = "voice-paste-e2e-no-such-model"\n'
"""ローカルの Whisper のモデルに存在しない名前を設定する（文字起こしワーカーがモデルを読み込めずに error を返す）。"""

OPENAI_SETTINGS = '[transcription]\nengine = "openai"\n'
"""文字起こしのエンジンを OpenAI API にする設定。"""

RETENTION_ONE_DAY_SETTINGS = "[history]\nretention_days = 1\n\n[logging]\nretention_days = 1\n"
"""履歴とログの保持期間を 1 日にする設定。"""

PREVIOUS_EXIT_TIMEOUT_SEC = 30.0
"""後から起動した後、前のプロセスが終わるまで待つ上限。"""

PREVIOUS_FINISHED_MESSAGE = "常駐サービスを終えた"
"""片付けを終えた（トレイのアイコンを削除した後）プロセスが書くログの文。"""

AI_CHAT_URL = "https://chatgpt.com/"
"""古い AI チャットの設定の送信先に書く URL（開かない）。"""

AI_CHAT_HOTKEY = "<ctrl>+<alt>+1"
"""古い AI チャットの設定の、出す送信先のホットキー。"""

AI_CHAT_TITLE = "ChatGPT"
"""古い AI チャットの設定の、出す送信先のタイトル。"""


def _old_ai_chat_settings() -> str:
    """古い AI チャットの設定（送信先 2 つ。うち 1 つは出さない）を書いた settings.toml の続きを返す。"""
    return (
        '[[outputs]]\nid = "paste_and_send"\n\n'
        '[[outputs]]\nid = "ai_chat"\n\n'
        f'[[outputs.targets]]\nname = "{AI_CHAT_TITLE}"\nurl = "{AI_CHAT_URL}"\n'
        f'hotkey = "{AI_CHAT_HOTKEY}"\nenabled = true\n\n'
        '[[outputs.targets]]\nname = "Claude"\nurl = "https://claude.ai/new"\n'
        'hotkey = "<ctrl>+<alt>+3"\nenabled = false\n'
    )


def _start_and_cancel_recording(app: ResidentApp) -> None:
    """録音開始のホットキーを押して録音が始まることを確かめ、取り消しのホットキーで待機中へ戻す。"""
    # 実行: 録音開始のホットキーが押された体で、登録された関数を呼ぶ
    app.press_start_hotkey()

    # 検証: トレイが録音中になり、録音の画面が出る
    assert app.wait_until(lambda: app.tray_state() == RECORDING)
    app.wait_widget("recording_window", QWidget)

    # 後始末: 取り消して待機中へ戻す
    app.press_registered_hotkey(CANCEL_HOTKEY)
    assert app.wait_until(lambda: app.tray_state() == IDLE)


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


@pytest.fixture
def occupied_port() -> Iterator[int]:
    """127.0.0.1 の空きポートを、ほかのプロセスが先に使っている状態にして、そのポートを返す。"""
    with socket.socket() as occupier:
        occupier.bind((LOOPBACK, 0))
        occupier.listen()
        yield int(occupier.getsockname()[1])


def test_normal(run_app: RunApp, tmp_path: Path) -> None:
    """起動すると、トレイが待機中になり、API がトークンに応え、`/web/` が許す Origin のブラウザの音声を受け付け、ワーカーが動き、録音開始のホットキーで録音が始まる（正常シナリオ）。"""
    # 準備: 録音の入力は無音の WAV。ブラウザが送信する音声は書き出した文を webm にしたもの
    wav_input = silence_input(tmp_path)
    web_audio = encode_audio(synthesize_speech(SPEECH_TEXT, tmp_path / "browser_speech.wav"), "webm")

    def case(app: ResidentApp) -> None:
        """起動した常駐アプリの、トレイ・トークン・API・ワーカー・ホットキーの受付を確かめる。"""
        # 検証
        assert app.tray_state() == IDLE
        assert (app.data_dir / "api_token").exists()
        # トークンのファイルから読んだ今回のトークンには応え、合わないトークン・トークン無しは断る
        assert app.post("/sessions/unknown/stop").status_code == 404
        assert app.post("/sessions/unknown/stop", authorized=False).status_code == 401
        assert (
            app.post(
                "/sessions/unknown/stop", headers={"Authorization": "Bearer previous-start-token"}
            ).status_code
            == 401
        )
        # `/web/` は、許す Origin から（トークン無しで）送信したブラウザの音声を受け付ける
        with httpx.Client(base_url=f"http://{LOOPBACK}:{app.port}") as http:
            accepted = http.post(
                "/web/transcriptions",
                files={"audio": ("recording.webm", web_audio, "audio/webm")},
                headers={"Host": f"localhost:{app.port}", "Origin": f"http://localhost:{app.port}"},
            )
        assert accepted.status_code == 202
        assert accepted.json()["job_id"]
        assert app.worker_pids() != set()
        # 録音開始のホットキーの受付が始まっていて、押すと録音が始まる
        assert app.hotkeys is not None
        assert UNUSED_START_HOTKEY in app.hotkeys.bindings
        _start_and_cancel_recording(app)
        assert wav_input.open_count == 1

    # 準備・実行: 起動し、イベントループの中で確かめる
    run_app(case, wav_input=wav_input)


def test_normal_when_previous_running(start_service: Callable[..., RealService]) -> None:
    """常駐中にもう一度起動すると、前の常駐サービスが終わり、新しい常駐サービスが待機中で出て、プロセスが 1 つだけになる（正常シナリオ）。"""
    # 準備: 前の常駐サービスを別プロセスで起動する
    previous = start_service()
    data_dir = previous.data_dir

    # 実行: 同じ置き場所でもう 1 つ起動し、入れ替わって立ち上がる（待機中のアイコンにした後のログ）まで待つ
    second_process = spawn_process(data_dir, stdout_name="stdout_second.log")
    wait_for_takeover(data_dir, second_process)

    # 検証: 前のプロセスが片付けでトレイのアイコンを削除して終わり、後のプロセスが動き、プロセスが 1 つだけ
    assert wait_until(lambda: not previous.is_running(), PREVIOUS_EXIT_TIMEOUT_SEC), (
        "前の常駐サービスが終わらなかった"
    )
    assert previous.process.returncode == 0
    assert PREVIOUS_FINISHED_MESSAGE in [str(record["msg"]) for record in read_log_records(data_dir)]
    assert second_process.poll() is None
    assert service_root_count(data_dir) == 1


def test_normal_when_expired_history_and_logs(run_app: RunApp) -> None:
    """保持期間を過ぎた日付の履歴とログは起動時に消え、今日の日付のものは残る（正常シナリオ）。"""
    # 準備: 保持期間を 1 日にし、2 日前と今日の履歴とログを置いて起動する
    dates: list[tuple[date, date]] = []

    def prepare(data_dir: Path) -> None:
        """起動の前に、2 日前と今日の履歴とログを置く。"""
        dates.append(_prepare_expired_files(data_dir))

    def case(app: ResidentApp) -> None:
        """起動時に、2 日前の履歴とログが消え、今日のものが残っていることを確かめる。"""
        expired, today = dates[0]
        # 検証
        assert not (app.data_dir / "history" / expired.strftime("%Y%m%d")).exists()
        assert not (app.data_dir / "log" / f"{expired.isoformat()}.log").exists()
        assert (app.data_dir / "history" / today.strftime("%Y%m%d")).is_dir()
        assert len(list((app.data_dir / "history" / today.strftime("%Y%m%d")).iterdir())) == 2
        today_log = app.data_dir / "log" / f"{today.isoformat()}.log"
        assert today_log.read_text(encoding="utf-8").startswith("古いログ\n")

    # 実行
    run_app(case, extra_settings=RETENTION_ONE_DAY_SETTINGS, prepare=prepare)


def test_error_when_engine_unavailable(run_app: RunApp) -> None:
    """文字起こしのエンジンを準備できなければ、トレイで起動の失敗が知らされ、ログに理由が書かれ、設定を開けて、録音は始まらない（異常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """起動に失敗した状態のトレイ・ログ・メニュー・ホットキーの受付を確かめる。"""
        # 検証: 起動の失敗がトレイに出て、ログに書かれ、プロセスは終わらずトレイのメニューから設定を開ける
        assert app.tray_state() == FAILED
        assert any(message.startswith("起動に失敗した（") for message in app.log_messages("ERROR"))
        assert app.menu_item_enabled("menu_settings")
        # 録音開始のホットキーの受付が始まっていないため、押しても録音が始まらない
        assert app.hotkeys is None
        assert app.window("recording_window") is None
        assert not (app.data_dir / "api_token").exists()

    # 準備・実行: 存在しないモデルの名前で起動する（トークンのファイルは書かれない）
    run_app(case, extra_settings=NO_SUCH_MODEL_SETTINGS)


def test_error_when_api_unavailable(run_app: RunApp, occupied_port: int, tmp_path: Path) -> None:
    """API の待ち受けを始められなければ、トレイで知らされ、ログに理由が書かれ、録音開始のホットキーで録音が始まる（異常シナリオ）。"""
    # 準備: 録音の入力は無音の WAV
    wav_input = silence_input(tmp_path)

    def case(app: ResidentApp) -> None:
        """API を使えない知らせ・ログ・ホットキーの受付を確かめる。"""
        # 検証
        assert app.wait_until(lambda: app.notified("api_unavailable"), UI_TIMEOUT_SEC)
        assert any(
            message.startswith("API の待ち受けを始められなかった（")
            for message in app.log_messages("ERROR")
        )
        assert not (app.data_dir / "api_token").exists()
        # 録音開始のホットキーの受付が始まっていて、押すと録音が始まる
        assert app.hotkeys is not None
        assert UNUSED_START_HOTKEY in app.hotkeys.bindings
        _start_and_cancel_recording(app)
        assert wav_input.open_count == 1

    # 準備・実行: API のポートをほかのプロセスが使っている状態で起動する（トークンのファイルは書かれない）
    run_app(case, port=occupied_port, wav_input=wav_input)


def test_normal_when_old_ai_chat_settings_remain(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """古い AI チャットの設定が残った settings.toml でも起動でき、出すとした送信先のボタンで確定すると送信先の URL を開いて貼り付け、Enter まで送信し、settings.toml は書き換わらない（正常シナリオ）。"""
    # 準備: 録音の入力は音声合成の WAV。貼り付けのキーとブラウザを開く呼び出しは控える
    extra_settings = _old_ai_chat_settings()
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """起動が止まらず、出すとした送信先のボタンだけが出て、確定すると送信先へ届くことを確かめる。"""
        # 検証: 起動が止まらない
        assert app.tray_state() == IDLE

        # 実行: 録音を始め、出すとした送信先のボタンで確定する
        app.press_start_hotkey()
        app.wait_widget("recording_window", QWidget)
        assert app.button_texts("preset_button_0") == [AI_CHAT_TITLE, format_hotkey(AI_CHAT_HOTKEY)]
        assert app.window("preset_button_1") is None
        app.press("preset_button_0")
        app.wait_processed()

        # 検証: 送信先の URL を開いて貼り付け、Enter まで送信し、settings.toml は書き換わっていない
        assert app.opened_urls == [AI_CHAT_URL]
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 1
        settings_file = app.data_dir / "settings.toml"
        assert settings_file.read_text(encoding="utf-8") == settings_text(app.port, extra_settings)

    # 実行: 古い設定で起動する
    run_app(
        case,
        extra_settings=extra_settings,
        wav_input=speech_input(tmp_path),
        keys=keys,
        capture_browser=True,
    )


def test_normal_when_openai(run_app: RunApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI API を使う設定では、環境変数が無くても設定の置き場所の API キーのファイルを読んで起動し、文字起こしワーカーを起動せず、録音開始のホットキーで録音が始まり、ログに API キーが書かれない（正常シナリオ（OpenAI API を使う設定））。"""
    # 準備: 環境変数は渡さず、設定の置き場所の secrets/openai_api_key に API キーだけを書いたファイルを置く
    monkeypatch.delenv(OPENAI_API_KEY_ENV, raising=False)
    wav_input = silence_input(tmp_path)

    def prepare(data_dir: Path) -> None:
        """起動の前に、API キーのファイルを置く。"""
        key_file = data_dir / "secrets" / "openai_api_key"
        key_file.parent.mkdir(parents=True)
        key_file.write_text(f"{API_KEY}\n", encoding="utf-8")

    def case(app: ResidentApp) -> None:
        """待機中のトレイ・ワーカー・ログ・ホットキーの受付を確かめる。"""
        # 検証
        assert app.tray_state() == IDLE
        assert app.worker_pids() == set()
        assert any("OpenAI API" in message for message in app.log_messages("INFO"))
        assert API_KEY not in app.log_text()
        # 録音開始のホットキーを押すと録音が始まる
        _start_and_cancel_recording(app)
        assert wav_input.open_count == 1

    # 実行
    run_app(case, extra_settings=OPENAI_SETTINGS, prepare=prepare, wav_input=wav_input)


def test_error_when_openai_api_key_missing(run_app: RunApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI API を使う設定で API キーが環境変数にもファイルにも無ければ、トレイで起動の失敗が知らされ、ログに読む環境変数の名前とファイルのパスが書かれ、設定を開けて、録音は始まらない（異常シナリオ（OpenAI の API キーが無い））。"""
    # 準備: 環境変数を渡さず、API キーのファイルも置かない
    monkeypatch.delenv(OPENAI_API_KEY_ENV, raising=False)

    def case(app: ResidentApp) -> None:
        """起動に失敗した状態のトレイ・ログ・メニュー・ホットキーの受付を確かめる。"""
        # 検証
        key_file = app.data_dir / "secrets" / "openai_api_key"
        assert app.tray_state() == FAILED
        errors = app.log_messages("ERROR")
        assert any(message.startswith("起動に失敗した（") for message in errors)
        assert any(OPENAI_API_KEY_ENV in message and str(key_file) in message for message in errors)
        assert app.menu_item_enabled("menu_settings")
        assert app.hotkeys is None
        assert app.window("recording_window") is None

    # 実行
    run_app(case, extra_settings=OPENAI_SETTINGS)


def test_error_when_local_whisper_not_installed(
    run_app: RunApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ローカルの Whisper を使う設定で faster-whisper のパッケージが無ければ、トレイで起動の失敗が知らされ、ログに local-whisper の extra を含めて環境を作り直すことが書かれ、ワーカーは起動せず、設定を開けて、録音は始まらない（異常シナリオ（ローカルの Whisper の依存が入っていない））。"""
    # 準備: faster-whisper のパッケージを見つけられないように差し替える
    real_find_spec = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object | None:
        """faster_whisper だけ見つからず、ほかは本物で探す。"""
        if name == "faster_whisper":
            return None
        return real_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)

    def case(app: ResidentApp) -> None:
        """起動に失敗した状態のトレイ・ログ・ワーカー・メニュー・ホットキーの受付を確かめる。"""
        # 検証
        assert app.tray_state() == FAILED
        assert any("local-whisper" in message for message in app.log_messages("ERROR"))
        assert app.worker_pids() == set()
        assert app.menu_item_enabled("menu_settings")
        assert app.hotkeys is None
        assert app.window("recording_window") is None

    # 実行: ローカルの Whisper（既定のエンジン）で起動する
    run_app(case)
