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
from voice_paste.features.correction import read_glossary_rows
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import load_settings
from voice_paste.shared.types import GlossaryEntry

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

GLOSSARY_FILE_NAME = "yogo.csv"
"""設定に用語集の一覧が無いときに読む、settings.toml と同じフォルダの用語集の CSV。"""

GLOSSARY_TWO_ROWS = "誤変換,正しい表記\nkuroudo,Claude\ngitto,Git\n"
"""用語集に 2 つある行（キーを打つ操作が確かな ASCII の語にしている）。"""

COMMENT_LINE = "# E2E: このコメントは保存しても残る"
"""COMMENTED_SETTINGS が持つコメント。"""


def _settings_file(app: ResidentApp) -> Path:
    """起動した常駐アプリの settings.toml のパス。"""
    return app.data_dir / "settings.toml"


def _toml(app: ResidentApp) -> dict[str, object]:
    """settings.toml を読む。"""
    return tomllib.loads(_settings_file(app).read_text(encoding="utf-8"))


def _glossary_file(app: ResidentApp) -> Path:
    """設定のフォルダの、今までの用語集の CSV（`prepare` で行を置く）。"""
    return app.data_dir / GLOSSARY_FILE_NAME


def _put_glossary(data_dir: Path) -> None:
    """起動の前に、設定のフォルダへ 2 行の用語集の CSV を置く。"""
    (data_dir / GLOSSARY_FILE_NAME).write_text(GLOSSARY_TWO_ROWS, encoding="utf-8")


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


def test_normal_when_edit_glossary(run_app: RunApp) -> None:
    """用語集の行を足し・書き換え・オフにして保存すると、用語集のファイルに書き戻され、再起動せずに補正へ効く（正常シナリオ）。

    補正は、動いている常駐アプリの補正に文字を渡して確かめる（マイクは開かない）。
    """

    def case(app: ResidentApp) -> None:
        """設定画面の「用語集」で、行を足し、1 つ目の行の正しい表記を書き換え、2 つ目の行をオフにして保存する。"""
        # 準備
        app.open_settings()
        app.select_group("用語集")

        # 実行
        app.press("add_glossary_entry_button")
        app.set_text("glossary_entry_wrong_2", "paison")
        app.set_text("glossary_entry_right_2", "Python")
        app.set_text("glossary_entry_right_0", "Claude Code")
        app.click("glossary_entry_on_1")
        app.press("save_button")

        # 検証
        assert app.wait_window_gone("settings_window")
        assert read_glossary_rows(_glossary_file(app)) == [
            GlossaryEntry(wrong="kuroudo", right="Claude Code"),
            GlossaryEntry(wrong="gitto", right="Git", enabled=False),
            GlossaryEntry(wrong="paison", right="Python"),
        ]
        assert COMMENT_LINE in _settings_file(app).read_text(encoding="utf-8")
        assert _toml(app)["recording"]["fade_sec"] == 1.5  # type: ignore[index]
        assert app.correct_text("kuroudo gitto paison") == "Claude Code gitto Python"

    run_app(case, extra_settings=COMMENTED_SETTINGS, prepare=_put_glossary)


def test_normal_when_switch_glossary_preset(run_app: RunApp) -> None:
    """用語集のプリセットを足して行を入れ、補正に使うプリセットを切り替えて保存すると、足したプリセットの用語集のファイルができ、再起動せずに補正へ効く（正常シナリオ）。

    補正は、動いている常駐アプリの補正に文字を渡して確かめる（マイクは開かない）。
    """

    def case(app: ResidentApp) -> None:
        """設定画面の「用語集」で、プリセットを足して名前と行を入れ、補正に使うプリセットを足したものに切り替えて保存する。"""
        # 準備
        before = _glossary_file(app).read_bytes()
        app.open_settings()
        app.select_group("用語集")

        # 実行
        app.press("add_glossary_button")
        app.set_text("glossary_name_1", "meeting")
        app.press("add_glossary_entry_button")
        app.set_text("glossary_entry_wrong_0", "paison")
        app.set_text("glossary_entry_right_0", "Python")
        app.click("glossary_active_1")
        app.press("save_button")

        # 検証
        assert app.wait_window_gone("settings_window")
        added = app.data_dir / "glossaries" / "glossary_1.csv"
        assert read_glossary_rows(added) == [GlossaryEntry(wrong="paison", right="Python")]
        assert _glossary_file(app).read_bytes() == before
        toml = _toml(app)
        assert toml["active_glossary"] == "meeting"
        assert [(item["name"], item["path"]) for item in toml["glossaries"]] == [  # type: ignore[attr-defined]
            ("yogo", GLOSSARY_FILE_NAME),
            ("meeting", "glossaries/glossary_1.csv"),
        ]
        assert COMMENT_LINE in _settings_file(app).read_text(encoding="utf-8")
        assert _toml(app)["recording"]["fade_sec"] == 1.5  # type: ignore[index]
        assert app.correct_text("kuroudo gitto paison") == "kuroudo gitto Python"

    run_app(case, extra_settings=COMMENTED_SETTINGS, prepare=_put_glossary)


HINT_PRESET_SETTINGS = (
    "\n[[hint_presets]]\n"
    'name = "開発"\n'
    'words = ["voice-paste", "Whisper"]\n'
    "enabled = true\n"
)
"""手がかりのプリセットを 1 つ（語が 2 つ・有効）持つ設定（`[api]` の続きに書く）。"""

HINT_LIMIT_BYTES = 222
"""有効なヒントの長さの上限（UTF-8 のバイト数）。"""

HINT_OVER_WORD_LENGTH = 209
"""1 つ目の語（11 バイト）と読点（3 バイト）と合わせて、つないだ長さが 223 バイトになる 2 つ目の語の長さ。"""


def test_normal_when_edit_hint_presets(run_app: RunApp) -> None:
    """手がかりのプリセットを足し・語を足して書き換え・無効にして保存すると、settings.toml に書かれ、再起動せずに次の文字起こしの手がかりへ効く（正常シナリオ）。

    手がかりは、動いている常駐アプリの文字起こしがエンジンへ渡す値で確かめる（マイクは開かない。録音を通した文字起こしは「録音を文字に起こす」の E2E）。
    """

    def case(app: ResidentApp) -> None:
        """設定画面の「表記のヒント」で、プリセットを 2 つ足して語を入れ、前からあるプリセットの語を足して書き換え、2 つ目に足したプリセットを無効にして保存する。"""
        # 準備
        assert app.hint_for_next_request() == "voice-paste、Whisper"
        app.open_settings()
        app.select_group("表記のヒント")

        # 実行（前からあるプリセットに語を足して 1 つ目の語を書き換え、有効なプリセットと、無効にするプリセットを足す）
        app.press("hint_word_add_0")
        app.set_text("hint_word_0_2", "tool")
        app.set_text("hint_word_0_0", "Claude")
        app.press("hint_preset_add")
        app.set_text("hint_preset_name_1", "meeting")
        app.press("hint_word_add_1")
        app.set_text("hint_word_1_0", "Git")
        app.press("hint_preset_add")
        app.set_text("hint_preset_name_2", "memo")
        app.press("hint_word_add_2")
        app.set_text("hint_word_2_0", "notes")
        app.click("hint_preset_enabled_2")
        app.press("save_button")

        # 検証
        assert app.wait_window_gone("settings_window")
        assert _toml(app)["hint_presets"] == [
            {"name": "開発", "words": ["Claude", "Whisper", "tool"], "enabled": True},
            {"name": "meeting", "words": ["Git"], "enabled": True},
            {"name": "memo", "words": ["notes"], "enabled": False},
        ]
        assert COMMENT_LINE in _settings_file(app).read_text(encoding="utf-8")
        assert _toml(app)["recording"]["fade_sec"] == 1.5  # type: ignore[index]
        assert app.hint_for_next_request() == "Claude、Whisper、tool、Git"

    run_app(case, extra_settings=HINT_PRESET_SETTINGS + COMMENTED_SETTINGS)


def test_error_when_hints_too_long(run_app: RunApp) -> None:
    """有効な手がかりをつないだ長さが 223 バイトになる語を入れて「保存」を押すと、書かず、長さの行の下にエラーを出して開いたままにし、常駐アプリの手がかりは変わらない（異常シナリオ）。"""

    def case(app: ResidentApp) -> None:
        """設定画面で、有効なプリセットの語を長くして「保存」を押す。"""
        # 準備
        before = _settings_file(app).read_bytes()
        app.open_settings()
        app.select_group("表記のヒント")
        app.set_text("hint_word_0_1", "w" * HINT_OVER_WORD_LENGTH)

        # 実行
        app.press("save_button")

        # 検証
        assert app.label("hint_length_error") == (
            f"有効なヒントが長すぎます（{HINT_LIMIT_BYTES + 1} / {HINT_LIMIT_BYTES} バイト）。"
            "語を減らすか、プリセットを無効にしてください。"
        )
        assert app.window("error_summary") is not None
        assert app.window("settings_window") is not None
        assert _settings_file(app).read_bytes() == before
        assert app.hint_for_next_request() == "voice-paste、Whisper"

    run_app(case, extra_settings=HINT_PRESET_SETTINGS + COMMENTED_SETTINGS)
