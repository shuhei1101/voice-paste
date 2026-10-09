"""単一ユースケース「設定を変える」の E2E テスト。

常駐アプリを pytest のプロセスの中で `main()` から起動し、トレイの「設定…」の項目を trigger して設定画面を開き、
クリックとキーを Qt のイベントで渡して欄・ボタンを操作する（欄は項目 ID `field_{キー}`、確認ダイアログは予約して答える）。
設定ファイルは起動した一時フォルダの `settings.toml`（`--data-dir`）で、普段使いの設定には触れない。
「保存して再起動」で起動し直す新しいプロセスだけは別プロセスで動き（Qt は offscreen）、ログとトークンのファイルで確かめる。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import wait_until
from tests.support.instances import started_count
from tests.support.real_service import read_token_file
from tests.support.resident_app import IDLE, ResidentApp, service_processes_for
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import load_settings

pytestmark = pytest.mark.real_machine

RunApp = Callable[..., ResidentApp]

COMMENTED_SETTINGS = (
    "# E2E: このコメントは保存しても残る\n"
    "[recording]\n"
    "fade_sec = 1.5\n"
    "\n"
    "[ui]\n"
    "wave_gain = 2.0\n"
)
"""既定と違う値とコメントを持つ設定（`[api]` の続きに書く）。"""

RESTART_KEY = "transcription.local_whisper.beam_size"
"""反映が restart の数値のキー。"""

RESET_TIMEOUT_SEC = 15.0
"""「既定に戻す」で settings.toml が既定の値で書かれるまで待つ上限。"""

RESTARTED_TIMEOUT_SEC = 180.0
"""再起動した新しい常駐アプリが待ち受けを始めるまで待つ上限。"""


def _settings_file(app: ResidentApp) -> Path:
    """起動した常駐アプリの settings.toml のパス。"""
    return app.data_dir / "settings.toml"


def _toml(app: ResidentApp) -> dict[str, object]:
    """settings.toml を読む。"""
    return tomllib.loads(_settings_file(app).read_text(encoding="utf-8"))


def _token(app: ResidentApp) -> object:
    """起動ごとのトークンのファイルから、トークンを読む（まだ無ければ None）。"""
    info = read_token_file(app.data_dir)
    return None if info is None else info["token"]


def test_normal_when_save_and_restart(run_app: RunApp) -> None:
    """反映が restart の設定を変えて「保存して再起動」を押すと、settings.toml が書かれ、前のプロセスが終わり、新しいプロセスが起動する（正常シナリオ）。

    変える設定は、モデルの取得を伴わない `transcription.local_whisper.beam_size`（反映は restart）にしている。
    """
    old_tokens: list[object] = []

    def case(app: ResidentApp) -> None:
        """設定画面で再起動で反映の欄を変え、「保存して再起動」を押す。"""
        # 準備
        old_tokens.append(_token(app))
        app.open_settings()
        app.select_group("文字起こし")
        app.set_field(RESTART_KEY, "5")
        assert app.window("restart_notice") is not None, "再起動で反映の知らせが出なかった"

        # 実行
        app.press("save_and_restart_button")

    # 準備・実行: 常駐アプリが自分で抜けるのを待つ
    app = run_app(case, expect_exit=True)

    # 検証: 前のプロセスが終わり、新しいプロセスが起動して待ち受けを始める
    assert _toml(app)["transcription"]["local_whisper"]["beam_size"] == 5  # type: ignore[index]
    assert app.exited_by_itself, "前のプロセスが終わらなかった"
    assert app.exit_code == 0
    assert wait_until(lambda: bool(service_processes_for(app.data_dir)), 60), (
        "新しいプロセスが起動しなかった"
    )
    assert wait_until(lambda: _token(app) not in (None, old_tokens[0]), RESTARTED_TIMEOUT_SEC), (
        "新しいプロセスが待ち受けを始めなかった"
    )
    assert wait_until(lambda: started_count(app.data_dir) == 2, RESTARTED_TIMEOUT_SEC)
    assert service_processes_for(app.data_dir) != []


def test_normal_when_reset(run_app: RunApp) -> None:
    """「既定に戻す」で確認に答えると、全てのキーが既定の値で書かれ、設定画面は開いたまま欄に既定の値が入る（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """設定画面で「既定に戻す」を押して確認に答える。"""
        # 準備
        app.open_settings()

        # 実行
        with app.answering("reset_dialog", "reset_button"):
            app.press("reset_button")

        # 検証
        assert app.wait_until(
            lambda: load_settings(_settings_file(app), SETTINGS_MODEL) == SETTINGS_MODEL(),
            RESET_TIMEOUT_SEC,
        )
        assert app.window("settings_window") is not None
        app.select_group("録音")
        assert app.field_value("recording.fade_sec") == "0.5"

    # 実行
    run_app(case, extra_settings=COMMENTED_SETTINGS)


def test_normal_when_cancel(run_app: RunApp) -> None:
    """欄を書き換えて「キャンセル」を押し、確認で「捨てて閉じる」を選ぶと、何も書かずに閉じる（正常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """設定画面で欄を書き換えて「キャンセル」を押し、捨てて閉じる。"""
        # 準備
        before = _settings_file(app).read_bytes()
        app.open_settings()
        app.select_group("録音")
        app.set_field("recording.fade_sec", "2.5")

        # 実行
        with app.answering("discard_dialog", "discard_button"):
            app.press("cancel_button")

        # 検証
        assert app.wait_window_gone("settings_window")
        assert _settings_file(app).read_bytes() == before
        assert app.tray_state() == IDLE

    run_app(case, extra_settings=COMMENTED_SETTINGS)


def test_error_when_invalid_value(run_app: RunApp) -> None:
    """通らない値（Enter までの秒数に abc）で「保存」を押すと、書かず、その欄の下にエラーを出して開いたままにする（異常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """設定画面で通らない値を入れて「保存」を押す。"""
        # 準備
        before = _settings_file(app).read_bytes()
        app.open_settings()
        app.select_group("出力先")
        app.set_field("outputs[0].enter_delay_sec", "abc")

        # 実行
        app.press("save_button")

        # 検証
        assert app.label("error_outputs[0].enter_delay_sec") == "数値を入れてください（例: 0.5）。"
        assert app.window("error_summary") is not None
        assert app.window("settings_window") is not None
        assert _settings_file(app).read_bytes() == before

    run_app(case, extra_settings=COMMENTED_SETTINGS)
