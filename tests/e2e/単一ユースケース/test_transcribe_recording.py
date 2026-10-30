"""単一ユースケース「録音を文字に起こす」の E2E テスト。

文字起こしの手がかりを渡す正常シナリオは、常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、ホットキーの入口（`start_local_session`）から録音を始める
（起動・トレイ・ホットキーの受付は通さない）。録音の入力は、Windows の音声合成（SAPI）で決めた文を書き出した WAV を流すものに
差し替え、マイクもスピーカーも通さない。システム音量・貼り付けのキー・通知は差し替える。
文字起こしはローカルの Whisper（GPU）で、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
文字起こしワーカーは、faster-whisper へ渡された hotwords を記録する入口（`tests/support/hotwords_probe_worker.py`）から起動し、
常駐アプリがワーカーへ送信した要求と、ワーカーが faster-whisper へ渡した値を確かめる。

それ以外のシナリオは、常駐アプリを pytest のプロセスの中で `main()` から起動し（`--data-dir` の一時フォルダ、Qt は offscreen）、
ホットキーが押された体で登録された関数を呼び、録音の画面・文字起こし中の表示・トレイは Qt のイベントで操作する。実機のマウス・キーボードは使わない。
録音の入力・システム音量・貼り付けのキーは差し替え（実機のマイクを開かず、システム音量を変えず、キーを送信しない）、
文字起こし中の表示が出たかは窓を見張って控え、失敗を知らせたことは知らせのログで、ログの置き場所を開くことは開く呼び出しに渡されたパスで確かめる。
API から始める録音の返送先は、テストが 127.0.0.1 に立てる受信先。
実機の Windows と GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyperclip
import pytest
from PySide6.QtWidgets import QApplication

import voice_paste.integrations.whisper.client as client_module
import voice_paste.main as main_module
from tests.integration.helpers import CallbackReceiver, make_audio
from tests.support.continuous import (
    SEGMENT_GAP_SEC,
    TROUBLED_SEGMENT,
    THREE_SENTENCES,
    assert_completed,
    assert_numbered_in_order,
    segments_of,
    sentences_of,
)
from tests.support.hotwords_probe_worker import PROBE_FILE_ENV
from tests.support.inprocess import (
    PROCESSED_TIMEOUT_SEC,
    FIRST_PRESET_CORRECTED_WORD,
    FIRST_PRESET_NAME,
    SECOND_PRESET_CORRECTED_WORD,
    SECOND_PRESET_NAME,
    SPEECH_TEXT,
    SPEECH_WORD,
    WORKER_READY_LOG,
    InProcessApi,
    InProcessApp,
    KeyLog,
    break_saved_recordings,
    encode_audio,
    fail_transcription_of_segment,
    kill_one_worker,
    kill_workers_twice,
    make_glossary_preset_settings,
    make_settings,
    silence_input,
    speech_input,
    speech_sequence_input,
    stub_transcription,
    synthesize_speech,
)
from tests.support.openai_endpoint import (
    API_KEY,
    TRANSCRIPTIONS_PATH,
    FakeOpenAIEndpoint,
)
from tests.support.real_service import REPO_ROOT, SOURCE_DIR
from tests.support.resident_app import IDLE, ResidentApp
from tests.support.web_body import sized_multipart_body
from voice_paste.features.correction import pick_glossary_preset
from voice_paste.integrations.openai.credentials import OPENAI_API_KEY_ENV
from voice_paste.integrations.openai.transcriber import OPENAI_MAX_AUDIO_BYTES
from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.errors import TranscriptionError
from voice_paste.shared.settings import (
    HintPresetSettings,
    OpenAISettings,
    TranscriptionSettings,
    load_settings,
)

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]
RunApp = Callable[..., ResidentApp]

GLOSSARY_FILE_NAME = "e2e.csv"
"""設定で選んでいる用語集の CSV の名前（settings.toml と同じフォルダ）。"""

SECOND_GLOSSARY_FILE_NAME = "second.csv"
"""設定で選んでいないプリセットが使う用語集の CSV の名前（settings.toml と同じフォルダ）。"""

GLOSSARY_SETTINGS = f'[[glossaries]]\nname = "e2e"\npath = "{GLOSSARY_FILE_NAME}"\n'
"""設定で選んでいる用語集のプリセット。"""

GLOSSARY_ROWS = "誤変換,正しい表記,使う\nテスト,試験,1\n天気,WEATHER,0\n"
"""用語集の行（話す内容で起きる誤変換のオンの行と、別の誤変換のオフの行）。"""

PRESET_GLOSSARY_SETTINGS = (
    f'[[glossaries]]\nname = "e2e"\npath = "{GLOSSARY_FILE_NAME}"\n'
    f'\n[[glossaries]]\nname = "second"\npath = "{SECOND_GLOSSARY_FILE_NAME}"\n'
    '\n[[glossary_presets]]\nname = "既定"\nglossaries = ["e2e"]\n'
    '\n[[glossary_presets]]\nname = "別"\nglossaries = ["second"]\n'
)
"""用語集のプリセットを 2 つ（それぞれ別の用語集を使う）持つ設定。設定で選んでいるプリセットのキーは書かず、1 つ目の「既定」を使う。"""

SECOND_GLOSSARY_ROWS = "誤変換,正しい表記,使う\nこれ,THIS,1\n"
"""2 つ目の用語集の行（話す内容で起きる、1 つ目の用語集とは別の誤変換のオンの行）。"""

SECOND_CORRECTED_WORD = "THIS"
"""2 つ目の用語集の行で置き換わった、正しい表記。"""

DELETE_ROW = "晴れ,,1\n"
"""話す内容に入る文言を誤変換にして、正しい表記を空にしたオンの行（削除する行）。"""

CORRECTED_WORD = "試験"
"""オンの行で置き換わった、正しい表記。"""

DELETED_WORD = THREE_SENTENCES[2][1]
"""削除する行の誤変換（起こした文字から消える言葉）。"""

OFF_ROW_WORD = THREE_SENTENCES[1][1]
"""オフの行の誤変換（置き換わらずに残る言葉）。"""

NO_VOICE_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も話し声と見なさず、起こした文字を空にする設定（無音の区間を除く閾値を最大にする）。"""

LONG_SPEECH_REPEAT = 10
"""ワーカーを止める間に起こし終わらないよう、読み上げた音をつなげる回数。"""

WORKER_RESTART_TIMEOUT_SEC = 120.0
"""やり直したワーカーも異常終了した後、文字起こしワーカーが立て直されるまで待つ上限。"""

PROBE_WORKER_MODULE = "tests.support.hotwords_probe_worker"
"""ワーカーの代わりに起動する、hotwords を記録する入口のモジュール。"""

PASTE_AND_SEND = "paste_and_send"
"""確定に選ぶ出力先の ID（貼り付けて送信）。"""

HINT_PRESETS = [
    HintPresetSettings(name="開発", words=["voice-paste", "Whisper"]),
    HintPresetSettings(name="秘密", words=["渡さない語"], enabled=False),
    HintPresetSettings(name="会議", words=["議事録", "返信"]),
]
"""手がかりのプリセット（語を 2 つずつ持つ有効なものが 2 つ、語を持つ無効のものが 1 つ。無効のものは有効の間に置く）。"""

EXPECTED_HINT = "voice-paste、Whisper、議事録、返信"
"""有効なプリセットの語を一覧の順に読点（、）でつないだ手がかり。"""

EDGE_PHRASE_SETTINGS = (
    '[[edge_phrases]]\ntext = "チャンネル登録*"\nposition = "end"\n\n'
    '[[edge_phrases]]\ntext = "ご視聴ありがとうございました"\nposition = "end"\n\n'
    '[[edge_phrases]]\ntext = "ありがとうございました"\nposition = "end"\n\n'
    '[[edge_phrases]]\ntext = "えーと"\nposition = "start"\n'
)
"""文頭・文末から削除する文言の一覧（上から「チャンネル登録*」「ご視聴ありがとうございました」「ありがとうございました」が文末、「えーと」が文頭）。"""

EDGE_PHRASE_TRANSCRIPT = (
    "えーと、ありがとうございました。本日の議題は予算です。\n"
    "以上です。ありがとうございました。ご視聴ありがとうございました。"
    "チャンネル登録よろしくお願いします。"
)
"""文字起こしが返す文字（文頭に「えーと」、文末に決まった文言が続く 2 行）。"""

EDGE_PHRASE_EXPECTED = "ありがとうございました。本日の議題は予算です。\n以上です。"
"""文頭・文末の文言を削除した後の文字。文頭の「えーと、」と文末の 3 つの文言が消え、位置が文末の行は文頭の「ありがとうございました。」に当たらない。"""


def _spy_transcribe_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """常駐アプリがワーカーへ送信する transcribe の要求の中身を、送信するたびに控える。"""
    requests: list[dict[str, Any]] = []
    original = WhisperWorkerClient._send

    def _send(self: WhisperWorkerClient, message_type: str, **payload: object) -> None:
        """transcribe なら中身を控えてから、本物で送信する。"""
        if message_type == "transcribe":
            requests.append(dict(payload))
        original(self, message_type, **payload)

    monkeypatch.setattr(WhisperWorkerClient, "_send", _send)
    return requests


def test_normal_when_hint(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """有効な手がかりのプリセットの語が、一覧の順に読点でつながってワーカーへ送信され、faster-whisper の hotwords に渡される（正常シナリオ（文字起こしの手がかりを渡す））。"""
    # 準備
    probe_file = tmp_path / "hotwords.jsonl"
    monkeypatch.setenv(PROBE_FILE_ENV, str(probe_file))
    # ワーカーが、この作業ツリーの src と、記録する入口（tests）を読めるようにする
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(SOURCE_DIR), str(REPO_ROOT)]))
    monkeypatch.setattr(client_module, "WORKER_MODULE", PROBE_WORKER_MODULE)
    requests = _spy_transcribe_requests(monkeypatch)
    settings = make_settings(only_paste_and_send=True).model_copy(update={"hint_presets": HINT_PRESETS})
    app = start_inprocess(settings=settings, wav_input=speech_input(tmp_path))

    # 実行
    app.start_hotkey()
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert app.wait_idle()
    [request] = requests
    assert request["hotwords"] == EXPECTED_HINT
    assert "渡さない語" not in request["hotwords"]
    passed = [json.loads(line) for line in probe_file.read_text(encoding="utf-8").splitlines()]
    assert passed == [EXPECTED_HINT]
    [recording] = app.history_files(".wav")
    [text_file] = app.history_files(".txt")
    assert recording.stem == text_file.stem
    assert text_file.read_text(encoding="utf-8") == pyperclip.paste()
    assert len(app.keys.pasted) == 1


def _put_glossary(data_dir: Path) -> None:
    """起動の前に、設定で選んでいる用語集の CSV を settings.toml と同じフォルダへ置く。"""
    (data_dir / GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS, encoding="utf-8")


def _put_glossary_with_delete_row(data_dir: Path) -> None:
    """起動の前に、削除する行を追加した用語集の CSV を settings.toml と同じフォルダへ置く。"""
    (data_dir / GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS + DELETE_ROW, encoding="utf-8")


def _put_preset_glossaries(data_dir: Path) -> None:
    """起動の前に、2 つのプリセットがそれぞれ使う用語集の CSV を settings.toml と同じフォルダへ置く。"""
    (data_dir / GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS, encoding="utf-8")
    (data_dir / SECOND_GLOSSARY_FILE_NAME).write_text(SECOND_GLOSSARY_ROWS, encoding="utf-8")


def _ready_messages(app: ResidentApp) -> list[str]:
    """文字起こしワーカーが ready になったときのログの文（立て直しを含む）を、ログから順に返す。"""
    return [message for message in app.log_messages() if message.startswith(WORKER_READY_LOG)]


def _kill_workers_twice(app: ResidentApp, first_pids: set[int]) -> int:
    """引いておいた番号のワーカーを止め、やり直しに立ったワーカーも ready になった直後に止める。止めた回数を返す。"""
    return kill_workers_twice(first_pids, lambda: _ready_messages(app))


def _failure_reasons(app: ResidentApp, event: str) -> list[str]:
    """ユーザーへの知らせ（event）のログに書かれた理由を、書かれた順に返す。"""
    prefix = f"ユーザーへの知らせ（{event}・"
    return [
        message.removeprefix(prefix).removesuffix("）")
        for message in app.log_messages()
        if message.startswith(prefix)
    ]


def _confirm_with_paste_and_send(app: ResidentApp) -> None:
    """録音を始め、録音の画面で「貼り付けて送信」を選んで確定する。"""
    app.start_recording()
    app.press("output_button_paste_and_send")


def test_normal(run_app: RunApp, tmp_path: Path, clipboard_sentinel: str) -> None:
    """確定した録音を起こすと、用語集のオンの行だけで誤変換が置き換わり、削除する行の誤変換が消え、区間ごとに改行で区切られ、履歴に残り、文字起こし中の表示が閉じて、届けられる（正常シナリオ）。"""
    # 準備: 文の間に無音を挟んだ WAV を実時間で流す（区間を 2 つ以上にする）
    wav_input = speech_sequence_input(
        tmp_path, sentences_of(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
    )
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """話し終えたら確定し、起こした文字・履歴・文字起こし中の表示・届け先を確かめる。"""
        # 実行
        app.start_recording()
        app.wait_played_out(wav_input)
        app.press("output_button_paste_and_send")
        assert app.wait_until(lambda: "transcribing_indicator" in app.seen_windows)
        app.wait_processed()

        # 検証
        text = app.history_text()
        assert CORRECTED_WORD in text
        assert SPEECH_WORD not in text
        assert DELETED_WORD not in text
        assert OFF_ROW_WORD in text
        assert len(text.splitlines()) >= 2
        assert pyperclip.paste() == text
        assert app.window("transcribing_indicator") is None
        assert len(keys.pasted) == 1

    run_app(
        case,
        extra_settings=GLOSSARY_SETTINGS,
        prepare=_put_glossary_with_delete_row,
        wav_input=wav_input,
        keys=keys,
    )


def test_normal_when_api_glossary_preset(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """API の開始で指定したプリセットの用語集で補正し、設定で選んでいるプリセットの用語集の誤変換は置き換わらずに残り、設定で選んでいるプリセットは変わらない（正常シナリオ（API で指定したプリセットで補正する））。"""

    def case(app: ResidentApp) -> None:
        """2 つ目のプリセットを指定して API で録音を完了し、届け先・履歴・設定で選んでいるプリセットを確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, glossary_preset="別")
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        [payload] = receiver.received
        assert payload["session_id"] == session_id
        assert payload["result"] == "transcribed"
        assert SECOND_CORRECTED_WORD in payload["text"]
        assert SPEECH_WORD in payload["text"]
        assert CORRECTED_WORD not in payload["text"]
        assert app.history_text() == payload["text"]
        settings = load_settings(app.data_dir / "settings.toml", SETTINGS_MODEL)
        assert pick_glossary_preset(settings, app.data_dir).name == "既定"

    run_app(
        case,
        extra_settings=PRESET_GLOSSARY_SETTINGS,
        prepare=_put_preset_glossaries,
        wav_input=speech_input(tmp_path),
    )


def test_normal_when_edge_phrases_removed(
    run_app: RunApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clipboard_sentinel: str
) -> None:
    """文字起こしが返した文字の文頭・文末から、一覧の文言が一覧の順に位置つきで消え、削除した文字がログに出て、文の途中の同じ文言は残り、起こした文字が届けられる（正常シナリオ（文頭・文末の決まった文言を削除する））。"""
    # 準備: 文字起こしは決まった文字を返し、録音の入力は WAV（中身は問わない）を流す
    monkeypatch.setattr(main_module, "transcribe", lambda *_args, **_options: EDGE_PHRASE_TRANSCRIPT)
    wav_input = speech_input(tmp_path)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """話し終えたら確定し、起こした文字・ログ・届け先を確かめる。"""
        # 実行
        app.start_recording()
        app.wait_played_out(wav_input)
        app.press("output_button_paste_and_send")
        app.wait_processed()

        # 検証
        text = app.history_text()
        assert text == EDGE_PHRASE_EXPECTED
        assert text.splitlines()[-1] == "以上です。"
        assert text.startswith("ありがとうございました。")
        assert "ご視聴" not in text
        removed = [
            message for message in app.log_messages() if message.startswith("文頭・文末の文言を削除した")
        ]
        assert len(removed) == 1
        assert "文頭: えーと、" in removed[0]
        assert "文末: チャンネル登録よろしくお願いします。" in removed[0]
        assert "文末: ご視聴ありがとうございました。" in removed[0]
        assert "文末: ありがとうございました。" in removed[0]
        assert pyperclip.paste() == text
        assert len(keys.pasted) == 1

    run_app(case, extra_settings=EDGE_PHRASE_SETTINGS, wav_input=wav_input, keys=keys)


def test_normal_when_worker_dies(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """文字起こしの途中でワーカーが落ちても、ワーカーを立て直して起こし直し、起こした文字が届き、常駐サービスは動き続ける（正常シナリオ（文字起こしワーカーが異常終了する））。"""
    # 準備: ワーカーを止める間に起こし終わらないよう、読み上げた音をつなげる
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定した直後にワーカーを 1 回止め、起こした文字・ワーカー・常駐サービスを確かめる。"""
        # 実行（止めるワーカーの番号は、確定の前に引いておく）
        workers_before = app.worker_pids()
        _confirm_with_paste_and_send(app)
        assert kill_one_worker(workers_before)
        app.wait_processed()

        # 検証: 起こした文字が届き、新しい子プロセスのワーカーが動き、常駐サービスが動き続けている
        assert pyperclip.paste() == app.history_text() != ""
        assert len(keys.pasted) == 1
        assert app.worker_pids() != set()
        assert app.worker_pids().isdisjoint(workers_before)
        assert app.tray_state() == IDLE
        assert app.post("/sessions/unknown/stop").status_code == 404

    run_app(case, wav_input=speech_input(tmp_path, repeat=LONG_SPEECH_REPEAT), keys=keys)


def test_error_when_worker_dies_again(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """やり直したワーカーも落ちると、失敗を知らせてワーカーを立て直し、録音は履歴に残り、常駐サービスは動き続ける（異常シナリオ（再起動したワーカーも異常終了する））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定した直後にワーカーを 2 回止め、知らせ・履歴・ワーカー・常駐サービスを確かめる。"""
        # 実行（止めるワーカーの番号は、確定の前に引いておく）
        workers_before = app.worker_pids()
        _confirm_with_paste_and_send(app)
        assert _kill_workers_twice(app, workers_before) >= 2
        app.wait_processed()

        # 検証
        assert app.notified("transcription_failed")
        assert pyperclip.paste() == clipboard_sentinel
        assert keys.pasted == []
        assert len(app.history_files(".wav")) == 1
        assert app.wait_until(lambda: app.worker_pids() != set(), WORKER_RESTART_TIMEOUT_SEC), (
            "文字起こしワーカーが立て直されなかった"
        )
        assert app.tray_state() == IDLE
        assert app.post("/sessions/unknown/stop").status_code == 404

    run_app(case, wav_input=speech_input(tmp_path, repeat=LONG_SPEECH_REPEAT), keys=keys)


def test_error_when_transcription_failed(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """読めない録音を確定すると、文字起こしの失敗を理由つきで知らせ、届けず、録音は履歴に残り、待機中に戻る（異常シナリオ（文字起こしに失敗））。"""
    # 準備: 保存した録音を読めない中身に書き換える
    break_saved_recordings(monkeypatch)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定して、知らせ・ログ・履歴・届け先・トレイを確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        app.wait_processed()

        # 検証
        [reason] = _failure_reasons(app, "transcription_failed")
        assert reason != "None"
        assert any(message.startswith("文字起こしに失敗した（") for message in app.log_messages("ERROR"))
        assert len(app.history_files(".wav")) == 1
        assert keys.pasted == []
        assert pyperclip.paste() == clipboard_sentinel
        assert app.window("transcribing_indicator") is None
        assert app.tray_state() == IDLE

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_error_when_transcription_empty(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """起こした文字が空なら、ダイアログを出さず、届けず、録音は履歴に残り、待機中に戻る（異常シナリオ（文字起こしの結果が空））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """無音の録音を確定して、ログ・ダイアログ・履歴・届け先・トレイを確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        app.wait_processed()

        # 検証
        assert any(message.startswith("文字起こしの結果が空だった（") for message in app.log_messages())
        assert app.unexpected_dialogs == []
        assert QApplication.activeModalWidget() is None
        assert len(app.history_files(".wav")) == 1
        assert keys.pasted == []
        assert pyperclip.paste() == clipboard_sentinel
        assert app.window("transcribing_indicator") is None
        assert app.tray_state() == IDLE

    run_app(case, extra_settings=NO_VOICE_SETTINGS, wav_input=silence_input(tmp_path), keys=keys)


def test_normal_when_api_transcription_empty(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """API から始めた録音の結果が空なら、空の文字を届け先へ渡し、録音は履歴に残り、ダイアログも文字起こし中の表示も出ない（正常シナリオ（API から始めた録音の結果が空））。"""

    def case(app: ResidentApp) -> None:
        """無音の録音を API で完了して、届け先・履歴・ダイアログ・文字起こし中の表示を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        [payload] = receiver.received
        assert payload["session_id"] == session_id
        assert payload["result"] == "transcribed"
        assert payload["text"] == ""
        assert len(app.history_files(".wav")) == 1
        assert app.unexpected_dialogs == []
        assert app.seen_windows == set()

    run_app(case, extra_settings=NO_VOICE_SETTINGS, wav_input=silence_input(tmp_path))


def test_error_when_api_transcription_failed(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """API から始めた録音の文字起こしに失敗すると、失敗を届け先へ渡し、録音は履歴に残り、ダイアログも文字起こし中の表示も出ない（異常シナリオ（API から始めた録音の文字起こしに失敗））。"""
    # 準備: 保存した録音を読めない中身に書き換える
    break_saved_recordings(monkeypatch)

    def case(app: ResidentApp) -> None:
        """読めない録音を API で完了して、届け先・履歴・ダイアログ・文字起こし中の表示を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        [payload] = receiver.received
        assert payload["session_id"] == session_id
        assert payload["result"] == "failed"
        assert payload["error"]
        assert len(app.history_files(".wav")) == 1
        assert app.unexpected_dialogs == []
        assert app.seen_windows == set()

    run_app(case, wav_input=speech_input(tmp_path))


def test_error_when_failure_notification_clicked(
    run_app: RunApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文字起こしの失敗の通知を押すと、ログの置き場所を開く（異常シナリオ（失敗の通知を押す））。"""
    # 準備: 保存した録音を読めない中身に書き換える
    break_saved_recordings(monkeypatch)

    def case(app: ResidentApp) -> None:
        """失敗を知らせた後で通知を押し、開くはずのフォルダとトレイを確かめる。"""
        # 準備
        _confirm_with_paste_and_send(app)
        app.wait_processed()
        assert app.notified("transcription_failed")

        # 実行
        app.click_notification()

        # 検証
        assert app.opened_folders == [app.data_dir / "log"]
        assert app.tray_state() == IDLE

    run_app(case, wav_input=speech_input(tmp_path), keys=KeyLog())


def test_normal_when_segments_in_order(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """連続録音の区間は、録音を続けたまま区切った順に起こされ、用語集で補正され、履歴に残り、文字起こし中の表示は開かない（正常シナリオ（区間を区切った順に起こす））。"""
    # 準備: 文の間に区切りの無音より長い無音を挟んだ WAV を実時間で流す
    wav_input = speech_sequence_input(
        tmp_path, sentences_of(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
    )

    def case(app: ResidentApp) -> None:
        """連続録音を始めて完了し、区間の文字・補正・履歴・文字起こし中の表示を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        app.wait_played_out(wav_input)
        app.complete_api_session(session_id)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 区間の文字が区切った順に届き、オンの行の誤変換だけが置き換わっている
        segments = segments_of(payloads)
        assert_numbered_in_order(segments, session_id)
        assert CORRECTED_WORD in segments[0]["text"]
        assert SPEECH_WORD not in segments[0]["text"]
        assert OFF_ROW_WORD in segments[1]["text"]
        assert THREE_SENTENCES[2][1] in segments[2]["text"]
        assert_completed(payloads, session_id, segment_count=len(THREE_SENTENCES))

        # 検証: 区間ごとの録音と起こした文字が履歴に残り、文字起こし中の表示は開いていない
        recordings = app.segment_recordings()
        assert len(recordings) == len(segments)
        for recording, segment in zip(recordings, segments, strict=True):
            assert recording.with_suffix(".txt").read_text(encoding="utf-8") == segment["text"]
        assert "transcribing_indicator" not in app.seen_windows

    run_app(
        case,
        extra_settings=GLOSSARY_SETTINGS,
        prepare=_put_glossary,
        wav_input=wav_input,
        keys=KeyLog(),
    )


def test_error_when_segment_transcription_failed(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """連続録音の区間の文字起こしに失敗すると、その区間の失敗を届け先へ渡し、ログに書き、録音は履歴に残り、次の区間を起こす（異常シナリオ（区間の文字起こしに失敗））。"""
    # 準備: 通し番号 2 の区間だけ文字起こしに失敗させる
    fail_transcription_of_segment(monkeypatch, TROUBLED_SEGMENT)
    wav_input = speech_sequence_input(
        tmp_path, sentences_of(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
    )

    def case(app: ResidentApp) -> None:
        """連続録音を始めて完了し、区間の失敗・次の区間・履歴・ログを確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        app.wait_played_out(wav_input)
        app.complete_api_session(session_id)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 通し番号 2 の区間の失敗が届き、通し番号 3 の区間がその後に起こされている
        segments = segments_of(payloads)
        assert [segment["result"] for segment in segments] == ["transcribed", "failed", "transcribed"]
        assert segments[TROUBLED_SEGMENT - 1]["error"]
        assert THREE_SENTENCES[2][1] in segments[2]["text"]

        # 検証: 通し番号 2 の区間の録音が履歴に残り、ログに失敗した理由と通し番号が書かれている
        assert len(app.segment_recordings()) == len(segments)
        assert any(
            message.startswith("区間の文字起こしに失敗した（")
            and session_id in message
            and message.endswith(f"・{TROUBLED_SEGMENT}）")
            for message in app.log_messages("ERROR")
        )

    run_app(case, wav_input=wav_input, keys=KeyLog())


BROWSER_GLOSSARY_FILE_NAME = "yogo.csv"
"""設定のフォルダに置く、今までの用語集の CSV の名前（設定で用語集を選んでいないときに使われる）。"""

BROWSER_AUDIO_FAILURE_TEXT = "ブラウザの音声の文字起こしに失敗させた"
"""差し替えた文字起こしが送出する例外のメッセージ。"""

NEXT_TEXT = "つぎの音声の文です"
"""失敗の後、エンジンを戻して続けて送信した音声が返す文。"""

JOB_POLL_SEC = 0.05
"""ジョブの状態を取りに行く間隔。"""


def _poll_job_until_finished(api: InProcessApi, job_id: str) -> tuple[dict[str, Any], list[float]]:
    """ジョブが終わる（done か failed）まで取りに行き、最後の本文と、取るたびの progress を返す。"""
    progresses: list[float] = []
    deadline = time.monotonic() + PROCESSED_TIMEOUT_SEC
    body = api.get_job(job_id).json()
    progresses.append(body["progress"])
    while body["state"] not in ("done", "failed") and time.monotonic() < deadline:
        time.sleep(JOB_POLL_SEC)
        body = api.get_job(job_id).json()
        progresses.append(body["progress"])
    return body, progresses


def _post_webm(api: InProcessApi, wav_path: Path, *, glossary_preset: str | None = None) -> str:
    """WAV を webm にして POST /web/transcriptions へ送信し（glossary_preset があれば用語集のプリセットの名前も送信し）、202 を確かめてジョブの ID を返す。"""
    response = api.post_web_audio(encode_audio(wav_path, "webm"), glossary_preset=glossary_preset)
    assert response.status_code == 202
    return str(response.json()["job_id"])


def test_normal_when_browser_audio(start_inprocess: StartInProcess, tmp_path: Path) -> None:
    """ブラウザから受けた音声が、用語集で補正した文字になって done になる。進みが増え、履歴に webm のままの音声と同じ名前の .txt が残り、貼り付けは起きない（正常シナリオ（ブラウザから受けた音声））。"""
    # 準備
    (tmp_path / BROWSER_GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS, encoding="utf-8")
    wav_path = synthesize_speech(SPEECH_TEXT, tmp_path / "browser_speech.wav")
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api()

    # 実行
    job_id = _post_webm(api, wav_path)
    body, progresses = _poll_job_until_finished(api, job_id)

    # 検証
    assert body["state"] == "done"
    assert CORRECTED_WORD in body["text"]
    assert SPEECH_WORD not in body["text"]
    assert progresses == sorted(progresses)
    assert all(0 <= progress <= 1 for progress in progresses)
    assert progresses[-1] == 1
    [recording] = app.history_files(".webm")
    [text_file] = app.history_files(".txt")
    assert recording.stem == text_file.stem
    assert text_file.read_text(encoding="utf-8") == body["text"]
    assert app.keys.pasted == []
    assert app.notifications.events == []


def test_error_when_browser_audio_transcription_failed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ブラウザから受けた音声の文字起こしに失敗すると failed になり、履歴に音声が残る。エンジンを戻して続けて送信した音声は done まで進み、知らせは出ない（異常シナリオ（ブラウザから受けた音声の文字起こしに失敗））。"""
    # 準備
    stub = stub_transcription(monkeypatch, NEXT_TEXT)
    stub.error = TranscriptionError(BROWSER_AUDIO_FAILURE_TEXT)
    wav_path = synthesize_speech(SPEECH_TEXT, tmp_path / "browser_speech.wav")
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api()
    caplog.set_level(logging.INFO)

    # 実行
    failed_id = _post_webm(api, wav_path)
    failed, _ = _poll_job_until_finished(api, failed_id)
    stub.error = None
    next_id = _post_webm(api, wav_path)
    next_body, _ = _poll_job_until_finished(api, next_id)

    # 検証
    assert failed["state"] == "failed"
    assert BROWSER_AUDIO_FAILURE_TEXT in failed["error"]
    assert len(app.history_files(".webm")) == 2
    assert any(
        failed_id in record.getMessage() and BROWSER_AUDIO_FAILURE_TEXT in record.getMessage()
        for record in caplog.records
    )
    assert next_body["state"] == "done"
    assert next_body["text"] == NEXT_TEXT
    assert app.notifications.events == []
    assert app.keys.pasted == []


def test_normal_when_browser_glossary_preset(start_inprocess: StartInProcess, tmp_path: Path) -> None:
    """ブラウザから受けた音声に 2 つ目のプリセットを指定すると、2 つ目のプリセットの用語集の言葉だけが置き換わり、1 つ目の用語集の言葉は残る。設定で選んでいるプリセットは 1 つ目のまま変わらない（正常シナリオ（ブラウザで選んだプリセットで補正する））。"""
    # 準備: 2 つのプリセットがそれぞれ別の用語集を使い、書き出した文の別々の言葉を置き換える行を 1 つずつ持つ。設定で選んでいるのは 1 つ目
    wav_path = synthesize_speech(SPEECH_TEXT, tmp_path / "browser_speech.wav")
    app = start_inprocess(
        settings=make_glossary_preset_settings(tmp_path), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api()

    # 実行
    job_id = _post_webm(api, wav_path, glossary_preset=SECOND_PRESET_NAME)
    body, _ = _poll_job_until_finished(api, job_id)

    # 検証
    assert body["state"] == "done"
    assert SECOND_PRESET_CORRECTED_WORD in body["text"]
    assert SPEECH_WORD in body["text"]
    assert FIRST_PRESET_CORRECTED_WORD not in body["text"]
    current = app.handlers.settings_store.get()
    assert pick_glossary_preset(current, app.paths.settings_file.parent).name == FIRST_PRESET_NAME


OPENAI_HINT_SETTINGS = '[[hint_presets]]\nname = "開発"\nwords = ["voice-paste", "Whisper"]\nenabled = true\n'
"""語を持つ有効な手がかりのプリセット 1 つ。"""

OPENAI_HINT = "voice-paste、Whisper"
"""OPENAI_HINT_SETTINGS の語を読点（、）でつないだ手がかり。"""

OPENAI_MODEL = "gpt-transcribe"
"""設定の OpenAI API のモデルの既定。"""

OPENAI_PREVIOUS_MODEL = "gpt-4o-mini-transcribe"
"""手がかりを prompt、言語を language で渡す前のモデル。"""

OVER_LIMIT_MARGIN_BYTES = 1_000
"""25 MB の上限を確実に超えるよう、上限に足す大きさ（バイト）。"""


def _openai_settings(endpoint: FakeOpenAIEndpoint, model: str | None = None) -> str:
    """文字起こしのエンジンを OpenAI API にし、ベース URL をテスト用のエンドポイントに向ける settings.toml の続きを返す。model を渡せばモデルも指定する（省けば既定のモデル）。"""
    model_line = "" if model is None else f'model = "{model}"\n'
    return (
        f'[transcription]\nengine = "openai"\n\n'
        f'[transcription.openai]\nbase_url = "{endpoint.base_url}"\n{model_line}'
    )


def test_normal_when_openai(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
    openai_endpoint: FakeOpenAIEndpoint,
) -> None:
    """OpenAI API を使う設定で確定した録音は、録音・既定のモデル・言語（languages[]）・手がかりの語（keywords[]）が API キーを付けて送信され、起こした文字の誤変換が用語集で置き換わって履歴に残り、ワーカーを起動せずに届けられる（正常シナリオ（OpenAI API で起こす））。"""
    # 準備: API キーは環境変数で渡し、テスト用のエンドポイントは用語集の誤変換を含む文字を返す
    monkeypatch.setenv(OPENAI_API_KEY_ENV, API_KEY)
    openai_endpoint.text = SPEECH_TEXT
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定して、エンドポイントが受けた要求・起こした文字・履歴・ワーカー・届け先を確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        assert app.wait_until(lambda: "transcribing_indicator" in app.seen_windows)
        app.wait_processed()

        # 検証: エンドポイントが受けた要求
        [request] = openai_endpoint.requests
        fields = request.form_fields()
        parts = request.form_parts()
        assert request.path == TRANSCRIPTIONS_PATH
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert fields["file"].startswith(b"RIFF")
        assert fields["model"] == OPENAI_MODEL.encode()
        assert [value for name, value in parts if name == "languages[]"] == [b"ja"]
        assert [value for name, value in parts if name == "keywords[]"] == [
            b"voice-paste",
            b"Whisper",
        ]
        assert "language" not in fields
        assert "prompt" not in fields
        # 起こした文字・履歴・ワーカー・届け先
        text = app.history_text()
        assert CORRECTED_WORD in text
        assert SPEECH_WORD not in text
        assert app.worker_pids() == set()
        assert pyperclip.paste() == text
        assert len(keys.pasted) == 1
        assert app.window("transcribing_indicator") is None

    run_app(
        case,
        extra_settings=GLOSSARY_SETTINGS + OPENAI_HINT_SETTINGS + _openai_settings(openai_endpoint),
        prepare=_put_glossary,
        wav_input=speech_input(tmp_path),
        keys=keys,
    )


def test_normal_when_openai_previous_model(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
    openai_endpoint: FakeOpenAIEndpoint,
) -> None:
    """設定のモデルが前のモデルなら、録音・モデル・言語（language）・手がかり（prompt）が API キーを付けて送信され、起こした文字が履歴に残って届けられる（正常シナリオ（OpenAI API の前のモデルで起こす））。"""
    # 準備: settings.toml でモデルに前のモデルを指定し、テスト用のエンドポイントは文字を返す
    monkeypatch.setenv(OPENAI_API_KEY_ENV, API_KEY)
    openai_endpoint.text = SPEECH_TEXT
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定して、エンドポイントが受けた要求・履歴・届け先を確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        assert app.wait_until(lambda: "transcribing_indicator" in app.seen_windows)
        app.wait_processed()

        # 検証: エンドポイントが受けた要求
        [request] = openai_endpoint.requests
        fields = request.form_fields()
        assert request.path == TRANSCRIPTIONS_PATH
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert fields["file"].startswith(b"RIFF")
        assert fields["model"] == OPENAI_PREVIOUS_MODEL.encode()
        assert fields["language"] == b"ja"
        assert fields["prompt"] == OPENAI_HINT.encode()
        assert "languages[]" not in fields
        assert "keywords[]" not in fields
        # 履歴・届け先
        text = app.history_text()
        assert SPEECH_TEXT in text
        assert pyperclip.paste() == text
        assert len(keys.pasted) == 1
        assert app.window("transcribing_indicator") is None

    run_app(
        case,
        extra_settings=OPENAI_HINT_SETTINGS + _openai_settings(openai_endpoint, OPENAI_PREVIOUS_MODEL),
        wav_input=speech_input(tmp_path),
        keys=keys,
    )


def test_error_when_openai_failed(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
    openai_endpoint: FakeOpenAIEndpoint,
) -> None:
    """OpenAI API が 401 を返すと、送信し直さずに、文字起こしの失敗を理由つきで知らせ、ログに API キーを書かず、録音は履歴に残り、届けず、待機中に戻る（異常シナリオ（OpenAI API が失敗を返す））。"""
    # 準備: テスト用のエンドポイントは 401（API キーの誤り）を返す
    monkeypatch.setenv(OPENAI_API_KEY_ENV, API_KEY)
    openai_endpoint.status = 401
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定して、知らせ・ログ・履歴・届け先・トレイを確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        app.wait_processed()

        # 検証
        [reason] = _failure_reasons(app, "transcription_failed")
        assert "401" in reason
        assert "invalid_api_key" in reason
        assert len(openai_endpoint.requests) == 1
        assert any(message.startswith("文字起こしに失敗した（") for message in app.log_messages("ERROR"))
        assert API_KEY not in app.log_text()
        assert len(app.history_files(".wav")) == 1
        assert keys.pasted == []
        assert pyperclip.paste() == clipboard_sentinel
        assert app.window("transcribing_indicator") is None
        assert app.tray_state() == IDLE

    run_app(
        case,
        extra_settings=_openai_settings(openai_endpoint),
        wav_input=speech_input(tmp_path),
        keys=keys,
    )


def test_error_when_openai_unsupported_audio(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    openai_endpoint: FakeOpenAIEndpoint,
) -> None:
    """OpenAI API が受けられない 25 MB を超える音声は、OpenAI API へ送信せずに failed になり、理由に上限が入り、履歴に音声が残る（異常シナリオ（OpenAI API が受けられない音声））。"""
    # 準備: 25 MB を超える webm を、履歴を残す設定の常駐アプリへ送信する
    monkeypatch.setenv(OPENAI_API_KEY_ENV, API_KEY)
    transcription = TranscriptionSettings(
        engine="openai", openai=OpenAISettings(base_url=openai_endpoint.base_url)
    )
    settings = make_settings(only_paste_and_send=True).model_copy(
        update={"transcription": transcription}
    )
    app = start_inprocess(settings=settings, wav_input=silence_input(tmp_path))
    api = app.start_web_api()
    caplog.set_level(logging.INFO)
    body = sized_multipart_body(
        make_audio("webm", tmp_path), OPENAI_MAX_AUDIO_BYTES + OVER_LIMIT_MARGIN_BYTES
    )

    # 実行
    response = api.post_web_body(body, chunked=True)
    assert response.status_code == 202
    job_id = str(response.json()["job_id"])
    failed, _ = _poll_job_until_finished(api, job_id)

    # 検証
    assert failed["state"] == "failed"
    assert "上限" in failed["error"]
    assert openai_endpoint.requests == []
    [recording] = app.history_files(".webm")
    assert recording.stat().st_size > OPENAI_MAX_AUDIO_BYTES
    assert any(
        job_id in record.getMessage() and "上限" in record.getMessage() for record in caplog.records
    )
