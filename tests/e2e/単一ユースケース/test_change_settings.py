"""単一ユースケース「設定を変える」の E2E テスト。

本物の常駐アプリを起動し、トレイの「設定…」から設定画面を開いて、UI Automation で欄・ボタンを操作する
（欄は項目 ID `field_{キー}`・`hotkey_{キー}`、確認ダイアログの中のボタンはダイアログの中から引く）。
設定ファイルは起動した一時フォルダの `settings.toml`（`--data-dir`）で、普段使いの設定には触れない。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support.app_driver import IDLE, AppDriver
from tests.support.desktop import wait_until

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

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


def _settings_file(app: AppDriver) -> Path:
    """起動した常駐アプリの settings.toml のパス。"""
    return app.service.data_dir / "settings.toml"


def _toml(app: AppDriver) -> dict[str, object]:
    """settings.toml を読む。"""
    return tomllib.loads(_settings_file(app).read_text(encoding="utf-8"))


def test_normal_when_save_and_restart(start_app: StartApp) -> None:
    """反映が restart の設定を変えて「保存して再起動」を押すと、settings.toml が書かれ、前のプロセスが終わり、新しいプロセスが起動する（正常シナリオ）。

    変える設定は、モデルの取得を伴わない `transcription.local_whisper.beam_size`（反映は restart）にしている。
    """
    # 準備
    app = start_app()
    data_dir = app.service.data_dir
    old_token = json.loads((data_dir / "api_token").read_text(encoding="utf-8"))["token"]
    app.open_settings()
    app.select_group("文字起こし")
    app.set_field(RESTART_KEY, "5")
    assert app.window("restart_notice") is not None, "再起動で反映の知らせが出なかった"

    # 実行
    app.press("save_and_restart_button")

    # 検証
    assert _toml(app)["transcription"]["local_whisper"]["beam_size"] == 5  # type: ignore[index]
    assert app.wait_exit(), "前のプロセスが終わらなかった"
    assert wait_until(lambda: bool(AppDriver.service_processes_for(data_dir)), 60), "新しいプロセスが起動しなかった"

    def _new_token() -> bool:
        """新しいプロセスが書いたトークンのファイルを読めるか。"""
        try:
            token = json.loads((data_dir / "api_token").read_text(encoding="utf-8"))["token"]
        except (OSError, ValueError, KeyError):
            return False
        return bool(token != old_token)

    assert wait_until(_new_token, 180), "新しいプロセスが待ち受けを始めなかった"
    assert wait_until(lambda: AppDriver.service_processes_for(data_dir) != [], 5)


def test_normal_when_reset(start_app: StartApp) -> None:
    """「既定に戻す」で確認に答えると、全てのキーが既定の値で書かれ、設定画面は開いたまま欄に既定の値が入る（正常シナリオ）。"""
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.settings import load_settings

    # 準備
    app = start_app(COMMENTED_SETTINGS)
    app.open_settings()
    app.press("reset_button")

    # 実行
    app.press_in("reset_dialog", "reset_button")

    # 検証
    assert wait_until(
        lambda: load_settings(_settings_file(app), SETTINGS_MODEL) == SETTINGS_MODEL(), 15
    )
    assert app.window("settings_window") is not None
    app.select_group("録音")
    assert app.field_value("recording.fade_sec") == "0.5"


def test_normal_when_cancel(start_app: StartApp) -> None:
    """欄を書き換えて「キャンセル」を押し、確認で「捨てて閉じる」を選ぶと、何も書かずに閉じる（正常シナリオ）。"""
    # 準備
    app = start_app(COMMENTED_SETTINGS)
    before = _settings_file(app).read_bytes()
    app.open_settings()
    app.select_group("録音")
    app.set_field("recording.fade_sec", "2.5")

    # 実行
    app.press("cancel_button")
    app.press_in("discard_dialog", "discard_button")

    # 検証
    assert app.wait_window_gone("settings_window")
    assert _settings_file(app).read_bytes() == before
    assert app.tray_state() == IDLE


def test_error_when_invalid_value(start_app: StartApp) -> None:
    """通らない値（Enter までの秒数に abc）で「保存」を押すと、書かず、その欄の下にエラーを出して開いたままにする（異常シナリオ）。"""
    # 準備
    app = start_app(COMMENTED_SETTINGS)
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
