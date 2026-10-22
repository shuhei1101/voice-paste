"""単一ユースケース「録音を文字に起こす」の E2E テスト。

文字起こしの手がかりを渡す正常シナリオは、常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、ホットキーの入口（`start_local_session`）から録音を始める
（起動・トレイ・ホットキーの受付は通さない）。録音の入力は、Windows の音声合成（SAPI）で決めた文を書き出した WAV を流すものに
差し替え、マイクもスピーカーも通さない。システム音量・貼り付けのキー・通知は差し替える。
文字起こしはローカルの Whisper（GPU）で、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
文字起こしワーカーは、faster-whisper へ渡された hotwords を記録する入口（`tests/support/hotwords_probe_worker.py`）から起動し、
常駐アプリがワーカーへ送った要求と、ワーカーが faster-whisper へ渡した値を確かめる。

それ以外のシナリオは、常駐アプリを pytest のプロセスの中で `main()` から起動し（`--data-dir` の一時フォルダ、Qt は offscreen）、
ホットキーが押された体で登録された関数を呼び、録音の画面・文字起こし中の表示・トレイは Qt のイベントで操作する。実機のマウス・キーボードは使わない。
録音の入力・システム音量・貼り付けのキーは差し替え（実機のマイクを開かず、システム音量を変えず、キーを送らない）、
文字起こし中の表示が出たかは窓を見張って控え、失敗を知らせたことは知らせのログで、ログの置き場所を開くことは開く呼び出しに渡されたパスで確かめる。
API から始める録音の返送先は、テストが 127.0.0.1 に立てる受け口。
実機の Windows と GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyperclip
import pytest
from PySide6.QtWidgets import QApplication

import voice_paste.integrations.whisper.client as client_module
from tests.integration.helpers import CallbackReceiver, wait_until
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
    SPEECH_WORD,
    WORKER_READY_LOG,
    WORKER_READY_TIMEOUT_SEC,
    InProcessApp,
    KeyLog,
    break_saved_recordings,
    fail_transcription_of_segment,
    kill_one_worker,
    make_settings,
    silence_input,
    speech_input,
    speech_sequence_input,
)
from tests.support.real_service import REPO_ROOT, SOURCE_DIR
from tests.support.resident_app import IDLE, ResidentApp
from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.shared.settings import HintPresetSettings

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]
RunApp = Callable[..., ResidentApp]

GLOSSARY_FILE_NAME = "e2e.csv"
"""設定で選んでいる用語集の CSV の名前（settings.toml と同じフォルダ）。"""

GLOSSARY_SETTINGS = f'[[glossaries]]\nname = "e2e"\npath = "{GLOSSARY_FILE_NAME}"\n'
"""設定で選んでいる用語集のプリセット。"""

GLOSSARY_ROWS = "誤変換,正しい表記,使う\nテスト,試験,1\n天気,WEATHER,0\n"
"""用語集の行（話す内容で起きる誤変換のオンの行と、別の誤変換のオフの行）。"""

DELETE_ROW = "ありがとう,,1\n"
"""話す内容に入る文言を誤変換にして、正しい表記を空にしたオンの行（消す行）。"""

CORRECTED_WORD = "試験"
"""オンの行で置き換わった、正しい表記。"""

DELETED_WORD = THREE_SENTENCES[2][1]
"""消す行の誤変換（起こした文字から消える言葉）。"""

OFF_ROW_WORD = THREE_SENTENCES[1][1]
"""オフの行の誤変換（置き換わらずに残る言葉）。"""

NO_VOICE_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も話し声と見なさず、起こした文字を空にする設定（無音の区間を除く閾値を最大にする）。"""

LONG_SPEECH_REPEAT = 10
"""ワーカーを止める間に起こし終わらないよう、読み上げた音をつなげる回数。"""

WORKER_RESTART_TIMEOUT_SEC = 120.0
"""やり直したワーカーも落ちた後、文字起こしワーカーが立て直されるまで待つ上限。"""

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


def _spy_transcribe_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """常駐アプリがワーカーへ送る transcribe の要求の中身を、送るたびに控える。"""
    requests: list[dict[str, Any]] = []
    original = WhisperWorkerClient._send

    def _send(self: WhisperWorkerClient, message_type: str, **payload: object) -> None:
        """transcribe なら中身を控えてから、本物で送る。"""
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
    """有効な手がかりのプリセットの語が、一覧の順に読点でつながってワーカーへ送られ、faster-whisper の hotwords に渡される（正常シナリオ（文字起こしの手がかりを渡す））。"""
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
    """起動の前に、消す行を足した用語集の CSV を settings.toml と同じフォルダへ置く。"""
    (data_dir / GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS + DELETE_ROW, encoding="utf-8")


def _ready_count(app: ResidentApp) -> int:
    """文字起こしワーカーが ready になった回数（立て直しを含む）を、ログから数える。"""
    return sum(message.startswith(WORKER_READY_LOG) for message in app.log_messages())


def _kill_workers_twice(app: ResidentApp) -> int:
    """文字起こしワーカーを止め、やり直しに立ったワーカーも ready になってから止める。止めた回数を返す。"""
    # 1. 立ち上がっているワーカーを止める（窓口が落ちたことに気づいて立て直す）
    ready_before = _ready_count(app)
    kills = int(kill_one_worker())

    # 2. やり直しのワーカーが ready になるのを待って止める（読み込みの途中で止めると、やり直しの前に失敗する）
    assert wait_until(lambda: _ready_count(app) > ready_before, WORKER_READY_TIMEOUT_SEC)
    return kills + int(kill_one_worker())


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
    """確定した録音を起こすと、用語集のオンの行だけで誤変換が置き換わり、消す行の誤変換が消え、区間ごとに改行で区切られ、履歴に残り、文字起こし中の表示が閉じて、届けられる（正常シナリオ）。"""
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


def test_normal_when_worker_dies(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """文字起こしの途中でワーカーが落ちても、ワーカーを立て直して起こし直し、起こした文字が届き、常駐サービスは動き続ける（正常シナリオ（文字起こしワーカーが落ちる））。"""
    # 準備: ワーカーを止める間に起こし終わらないよう、読み上げた音をつなげる
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定した直後にワーカーを 1 回止め、起こした文字・ワーカー・常駐サービスを確かめる。"""
        # 実行
        workers_before = app.worker_pids()
        _confirm_with_paste_and_send(app)
        assert kill_one_worker()
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
    """やり直したワーカーも落ちると、失敗を知らせてワーカーを立て直し、録音は履歴に残り、常駐サービスは動き続ける（異常シナリオ（やり直したワーカーも落ちる））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """確定した直後にワーカーを 2 回止め、知らせ・履歴・ワーカー・常駐サービスを確かめる。"""
        # 実行
        _confirm_with_paste_and_send(app)
        assert _kill_workers_twice(app) >= 2
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
