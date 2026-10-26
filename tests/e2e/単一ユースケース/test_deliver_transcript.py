"""単一ユースケース「起こした文字を届ける」の E2E テスト。

常駐アプリを pytest のプロセスの中で `main()` から起動し（`--data-dir` の一時フォルダ、Qt は offscreen）、
ホットキーが押された体で登録された関数を呼び、録音の画面・文字起こし中の表示・トレイは Qt のイベントで操作する。実機のマウス・キーボードは使わない。
録音の入力は Windows の音声合成（SAPI）で決めた文を書き出した WAV（か無音の WAV）に、システム音量は呼ばれた値を控えるものに、
貼り付けのキーと Enter は送ったキーと Enter に添えた修飾キーを控えるものに、ブラウザを開く呼び出しは渡された URL を控えるものに差し替え、
実機のマイクを開かず、システム音量を変えず、キーを送らず、Microsoft Edge を開かない。
貼り付け先の入力欄に入ることは、クリップボードの文字と、控えた貼り付けのキー・Enter・修飾キーで確かめる。
コピーの完了の通知が出たことは知らせのログで確かめ、通知を押す操作は通知が押されたシグナルを渡す。
文字起こしはローカルの Whisper（GPU）で、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
返送先・送り先は、テストが 127.0.0.1 に立てる受け口。
「Enter と一緒に修飾キーを押す」の「Ctrl が押されたままになっていない」は、キーを送る部品の単体テストが確かめる。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pyperclip
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from tests.integration.helpers import CallbackReceiver
from tests.support.continuous import (
    SEGMENT_GAP_SEC,
    TROUBLED_SEGMENT,
    THREE_SENTENCES,
    Payload,
    assert_completed,
    assert_each_word,
    assert_ended,
    assert_numbered_in_order,
    segments_of,
    sentences_of,
    words_of,
)
from tests.support.inprocess import (
    SPEECH_WORD,
    KeyLog,
    WavInput,
    break_saved_recordings,
    fail_transcription_of_segment,
    silence_input,
    speech_input,
    speech_sequence_input,
)
from tests.support.real_service import LOOPBACK, free_port
from tests.support.resident_app import IDLE, ResidentApp
from voice_paste.features.outputs.callback import service as callback_service
from voice_paste.features.outputs.callback.service import CALLBACK_RETRY_COUNT
from voice_paste.ui.windows.transcribing_indicator import COPY_HINT_TEXT, HINT_TEXT

pytestmark = pytest.mark.real_machine

RunApp = Callable[..., ResidentApp]

BROWSER_URL = "https://example.com/chat"
"""ブラウザ添付のプリセットに書く URL（開かない。控えるだけ）。"""

BROWSER_TITLE = "e2e-browser"
ENDPOINT_TITLE = "e2e-endpoint"
"""足すプリセットのタイトル。"""

OVERWRITTEN_TEXT = "voice-paste-e2e-overwritten"
"""通知が出ている間に、ほかのアプリがクリップボードへコピーした文字（起こした文字と重ならない）。"""

SWITCH_REPEAT = 10
"""切り替えるまで文字起こしが続くよう、音声合成の文を繰り返す回数。"""

ENDPOINT_RESPONSE_DELAY_SEC = 3.0
"""応えない送り先が、受け取ってから応えるまで待つ秒数（設定の既定のタイムアウト 1.5 秒より長い）。"""

NO_RESEND_WAIT_MS = 2000
"""送り先に届かなかった後、送り直さないことを確かめるために待つ時間。"""

SHORT_RETRY_BASE_SEC = 0.05
"""テストで待てる返送の再送の間隔の基数。"""

NO_SPEECH_SEC = 4.0
"""話さないまま完了するときに流す無音の長さ。"""

SESSION_LIMIT_SEC = 60
"""設定で許す連続録音のセッションの上限時間の下限。"""

LIMIT_TAIL_SEC = 70.0
"""上限での打ち切りのとき、読み上げを流し終えた後に流し続ける無音の長さ（上限時間より長くする）。"""

ENTER_WITH_CTRL_SETTINGS = '[[outputs]]\nid = "paste_and_send"\nenter_modifiers = ["ctrl"]\n'
"""貼り付けて送信の Enter と一緒に押す修飾キーを Ctrl だけにした設定。"""

NO_VOICE_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も話し声と見なさず、起こした文字を空にする設定（無音の区間を除く閾値を最大にする）。"""

LIMIT_SETTINGS = f"[api.continuous]\nsession_limit_sec = {SESSION_LIMIT_SEC}\n"
"""連続録音のセッションの上限時間を、設定で許す下限にする設定。"""


def _browser_preset_settings(*, send_enter: bool) -> str:
    """ブラウザ添付のプリセットを 1 つ追加する設定を返す。"""
    return (
        "[[presets]]\n"
        'kind = "browser"\n'
        f'title = "{BROWSER_TITLE}"\n'
        f'url = "{BROWSER_URL}"\n'
        f"send_enter = {str(send_enter).lower()}\n"
    )


def _endpoint_preset_settings(url: str) -> str:
    """エンドポイントへ送信のプリセットを 1 つ追加する設定を返す。"""
    return f'[[presets]]\nkind = "endpoint"\ntitle = "{ENDPOINT_TITLE}"\nurl = "{url}"\n'


def _record_and_confirm(app: ResidentApp, button: str) -> str:
    """録音を始め、録音の画面の button で確定して、セッションの ID を返す。"""
    app.start_recording()
    session = app.current_session()
    assert session is not None
    app.press(button)
    return session.id


def _single_payload(receiver: CallbackReceiver, session_id: str, result: str) -> Payload:
    """返送先の受け口に 1 回だけ、このセッションの返送が届いていることを確かめて、その中身を返す。"""
    [payload] = receiver.received
    assert payload["session_id"] == session_id
    assert payload["result"] == result
    assert payload["segment_number"] is None
    assert payload["segment_count"] is None
    return payload


def _is_checked(app: ResidentApp, name: str) -> bool:
    """文字起こし中の表示の切り替えのボタンが、選んだ状態か。"""
    return app.wait_widget(name, QPushButton).isChecked()


def test_normal(run_app: RunApp, tmp_path: Path, clipboard_sentinel: str) -> None:
    """「貼り付けて送信」を選ぶと、起こした文字がクリップボードに入り、貼り付けのキーと修飾キーなしの Enter が送られ、待機中に戻る（正常シナリオ）。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「貼り付けて送信」で確定し、届け先とトレイを確かめる。"""
        # 実行
        _record_and_confirm(app, "output_button_paste_and_send")
        app.wait_processed()

        # 検証
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 1
        assert keys.enter_modifiers == [()]
        assert app.tray_state() == IDLE

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_paste_only(run_app: RunApp, tmp_path: Path, clipboard_sentinel: str) -> None:
    """「貼り付けのみ」を選ぶと、起こした文字がクリップボードに入り、貼り付けのキーだけが送られ、Enter は送られない（正常シナリオ（貼り付けのみ））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「貼り付けのみ」で確定し、届け先を確かめる。"""
        # 実行
        _record_and_confirm(app, "output_button_paste_only")
        app.wait_processed()

        # 検証
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 0

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_copy_only(run_app: RunApp, tmp_path: Path, clipboard_sentinel: str) -> None:
    """「コピーのみ」を選ぶと、起こした文字がクリップボードに入り、貼り付けのキーも Enter も送られず、コピーの完了の通知が出る（正常シナリオ（コピーのみ））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「コピーのみ」で確定し、届け先と通知を確かめる。"""
        # 実行
        _record_and_confirm(app, "output_button_copy_only")
        app.wait_processed()

        # 検証
        assert SPEECH_WORD in pyperclip.paste()
        assert keys.pasted == []
        assert keys.enters == 0
        assert app.notified("copy_completed")

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_browser_preset(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """Enter まで送信するブラウザ添付のプリセットを選ぶと、プリセットの URL を開いて貼り付け、修飾キーなしの Enter を送る（正常シナリオ（ブラウザ添付のプリセット））。"""
    # 準備: 貼り付けて送信は Ctrl をオンにしている（プリセットには当てない）
    extra_settings = ENTER_WITH_CTRL_SETTINGS + _browser_preset_settings(send_enter=True)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """プリセットのボタンで確定し、開いた URL と届け先を確かめる。"""
        # 実行
        _record_and_confirm(app, "preset_button_0")
        app.wait_processed()

        # 検証
        assert app.opened_urls == [BROWSER_URL]
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 1
        assert keys.enter_modifiers == [()]

    run_app(
        case,
        extra_settings=extra_settings,
        wav_input=speech_input(tmp_path),
        keys=keys,
        capture_browser=True,
    )


def test_normal_when_browser_preset_paste_only(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """Enter まで送らないブラウザ添付のプリセットを選ぶと、プリセットの URL を開いて貼り付けるだけで、Enter は送らない（正常シナリオ（ブラウザ添付のプリセット・貼り付けだけ））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """プリセットのボタンで確定し、開いた URL と届け先を確かめる。"""
        # 実行
        _record_and_confirm(app, "preset_button_0")
        app.wait_processed()

        # 検証
        assert app.opened_urls == [BROWSER_URL]
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 0

    run_app(
        case,
        extra_settings=_browser_preset_settings(send_enter=False),
        wav_input=speech_input(tmp_path),
        keys=keys,
        capture_browser=True,
    )


def test_normal_when_return_to_caller(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver, clipboard_sentinel: str
) -> None:
    """API から始めた録音は、起こした文字を返送先へ 1 回返し、クリップボードも貼り付け先も変えない（正常シナリオ（呼び出し元へ返す））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """API で録音して完了し、返送先の受け口に届いた中身を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        payload = _single_payload(receiver, session_id, "transcribed")
        assert SPEECH_WORD in payload["text"]
        assert payload["error"] is None
        assert pyperclip.paste() == clipboard_sentinel
        assert keys.pasted == []
        assert keys.enters == 0
        assert app.tray_state() == IDLE

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_return_empty_text(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """API から始めた録音の文字起こしの結果が空でも、空の文字を返送先へ 1 回返す（正常シナリオ（呼び出し元へ空の文字を返す））。"""

    def case(app: ResidentApp) -> None:
        """無音の録音を API で完了し、返送先の受け口に届いた中身を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        payload = _single_payload(receiver, session_id, "transcribed")
        assert payload["text"] == ""
        assert payload["error"] is None
        assert app.tray_state() == IDLE

    run_app(case, extra_settings=NO_VOICE_SETTINGS, wav_input=silence_input(tmp_path))


def test_error_when_return_failure(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """API から始めた録音の文字起こしに失敗すると、失敗したことを返送先へ 1 回返す（異常シナリオ（呼び出し元へ失敗を返す））。"""
    # 準備: 保存した録音を読めない中身に書き換える
    break_saved_recordings(monkeypatch)

    def case(app: ResidentApp) -> None:
        """読めない録音を API で完了し、返送先の受け口に届いた中身を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        payload = _single_payload(receiver, session_id, "failed")
        assert payload["text"] == ""
        assert payload["error"]
        assert app.tray_state() == IDLE

    run_app(case, wav_input=speech_input(tmp_path))


def test_error_when_callback_unreachable(run_app: RunApp, tmp_path: Path) -> None:
    """返送先に届かなければ、返送を決めた回数まで試し、ログに書いて待機中に戻り、履歴は残って次の録音を始められる（異常シナリオ（返送先に届かない））。"""
    # 準備: 何も待ち受けていないポートを返送先にする
    unreachable_url = f"http://{LOOPBACK}:{free_port()}/result"

    def case(app: ResidentApp) -> None:
        """API で録音して完了し、ログ・履歴・次の録音を確かめる。"""
        # 実行
        session_id = app.start_api_session(unreachable_url)
        app.complete_api_session(session_id)
        app.wait_processed()

        # 検証
        errors = app.log_messages("ERROR")
        assert any("返送先に届かなかった" in message and session_id in message for message in errors)
        assert SPEECH_WORD in app.history_text()
        assert app.tray_state() == IDLE
        assert app.start_api_session(unreachable_url)

    run_app(case, wav_input=speech_input(tmp_path))


def test_normal_when_endpoint_preset(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver, clipboard_sentinel: str
) -> None:
    """エンドポイントへ送信のプリセットを選ぶと、起こした文字を送り先へ 1 回送り、クリップボードも貼り付け先も変えない（正常シナリオ（エンドポイントへ送信のプリセット））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """プリセットのボタンで確定し、送り先の受け口に届いた中身を確かめる。"""
        # 実行
        session_id = _record_and_confirm(app, "preset_button_0")
        app.wait_processed()

        # 検証
        [payload] = receiver.received
        assert payload["session_id"] == session_id
        assert payload["result"] == "transcribed"
        assert SPEECH_WORD in payload["text"]
        assert payload["error"] is None
        assert pyperclip.paste() == clipboard_sentinel
        assert keys.pasted == []
        assert keys.enters == 0
        assert app.tray_state() == IDLE

    run_app(
        case,
        extra_settings=_endpoint_preset_settings(receiver.url),
        wav_input=speech_input(tmp_path),
        keys=keys,
    )


def test_error_when_endpoint_unreachable(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """送り先がタイムアウトまでに応えなければ、届けられなかったことを知らせてログに書き、送り直さず、履歴は残って次の録音を始められる（異常シナリオ（送信先に届かない））。"""
    # 準備: 送り先の受け口が、設定のタイムアウトより長く応えない
    receiver.delay_sec = ENDPOINT_RESPONSE_DELAY_SEC

    def case(app: ResidentApp) -> None:
        """プリセットのボタンで確定し、知らせ・ログ・送った回数・履歴・次の録音を確かめる。"""
        # 実行
        session_id = _record_and_confirm(app, "preset_button_0")
        app.wait_processed()
        QTest.qWait(NO_RESEND_WAIT_MS)

        # 検証
        assert app.notified("delivery_failed")
        errors = app.log_messages("ERROR")
        assert any("出力先へ届けられなかった" in message and session_id in message for message in errors)
        assert len(receiver.received) == 1
        assert SPEECH_WORD in app.history_text()
        assert app.tray_state() == IDLE
        app.start_recording()
        app.press("cancel_button")
        assert app.wait_until(lambda: app.tray_state() == IDLE)

    run_app(
        case,
        extra_settings=_endpoint_preset_settings(receiver.url),
        wav_input=speech_input(tmp_path),
        keys=KeyLog(),
    )


def _three_sentences_input(tmp_path: Path) -> WavInput:
    """文の間に区切りの無音より長い無音を挟んだ 3 文の WAV を、実時間で流す録音の入力にする。"""
    return speech_sequence_input(tmp_path, sentences_of(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC)


def _no_speech_input(tmp_path: Path) -> WavInput:
    """何も話さない無音の WAV を、実時間で流す録音の入力にする。"""
    return silence_input(tmp_path, seconds=NO_SPEECH_SEC, realtime=True)


def _three_sentences_then_silence_input(tmp_path: Path) -> WavInput:
    """3 文の WAV の後に、上限時間より長い無音を続けた録音の入力にする。"""
    return speech_sequence_input(
        tmp_path,
        sentences_of(THREE_SENTENCES),
        gap_sec=SEGMENT_GAP_SEC,
        tail_silence_sec=LIMIT_TAIL_SEC,
    )


def _finish_by_complete(app: ResidentApp, session_id: str, wav_input: WavInput) -> None:
    """流し終えるのを待って、API の完了で連続録音を終える。"""
    app.wait_played_out(wav_input)
    app.complete_api_session(session_id)


def _finish_by_limit(app: ResidentApp, session_id: str, wav_input: WavInput) -> None:
    """完了を呼ばず、上限時間で打ち切られるのを待つ。"""


def test_normal_when_return_segments(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver, clipboard_sentinel: str
) -> None:
    """連続録音は、区間の文字を区切った順に通し番号つきで返送先へ 1 回ずつ返し、クリップボードも貼り付け先も変えない（正常シナリオ（区間ごとに呼び出し元へ返す））。"""
    # 準備
    wav_input = _three_sentences_input(tmp_path)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """連続録音を始めて完了し、返送先の受け口に届いた区間を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        _finish_by_complete(app, session_id, wav_input)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証
        segments = segments_of(payloads)
        assert_numbered_in_order(segments, session_id)
        assert_each_word(segments, words_of(THREE_SENTENCES))
        assert pyperclip.paste() == clipboard_sentinel
        assert keys.pasted == []
        assert keys.enters == 0

    run_app(case, wav_input=wav_input, keys=keys)


@dataclass(frozen=True)
class ContinuousEnd:
    """連続録音の終わりのケース。流す録音の入力・設定・終わらせ方と、返送先へ届くはずの終わり。"""

    make_input: Callable[[Path], WavInput]
    finish: Callable[[ResidentApp, str, WavInput], None]
    extra_settings: str
    result: str
    segment_count: int


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            ContinuousEnd(
                make_input=_three_sentences_input,
                finish=_finish_by_complete,
                extra_settings="",
                result="completed",
                segment_count=len(THREE_SENTENCES),
            ),
            id="completed",
        ),
        pytest.param(
            ContinuousEnd(
                make_input=_no_speech_input,
                finish=_finish_by_complete,
                extra_settings="",
                result="completed",
                segment_count=0,
            ),
            id="completed_without_segments",
        ),
        pytest.param(
            ContinuousEnd(
                make_input=_three_sentences_then_silence_input,
                finish=_finish_by_limit,
                extra_settings=LIMIT_SETTINGS,
                result="truncated",
                segment_count=len(THREE_SENTENCES),
            ),
            id="truncated",
        ),
    ],
)
def test_normal_when_return_continuous_end(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver, scenario: ContinuousEnd
) -> None:
    """連続録音が完了か上限で終わると、最後の区間の後に、終わった理由と区間の数を 1 回返し、待機中に戻って次の録音を始められる（正常シナリオ（連続録音の終わりを返す））。"""
    # 準備
    wav_input = scenario.make_input(tmp_path)

    def case(app: ResidentApp) -> None:
        """連続録音を始めて終わらせ、返送先の受け口に届いた終わりを確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        scenario.finish(app, session_id, wav_input)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 終わりが最後の区間の後に 1 回届き、区間の数が届けた区間の数と一致する
        assert_ended(payloads, session_id, scenario.result, scenario.segment_count)
        assert len(segments_of(payloads)) == scenario.segment_count
        assert app.tray_state() == IDLE
        assert app.start_api_session(receiver.url)

    run_app(case, extra_settings=scenario.extra_settings, wav_input=wav_input, keys=KeyLog())


def test_error_when_return_segment_failure(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """連続録音の区間の文字起こしに失敗すると、その区間の失敗を通し番号つきで返送先へ返し、その後の区間を続けて返す（異常シナリオ（区間の失敗を呼び出し元へ返す））。"""
    # 準備: 通し番号 2 の区間だけ文字起こしに失敗させる
    fail_transcription_of_segment(monkeypatch, TROUBLED_SEGMENT)
    wav_input = _three_sentences_input(tmp_path)

    def case(app: ResidentApp) -> None:
        """連続録音を始めて完了し、返送先の受け口に届いた区間を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        _finish_by_complete(app, session_id, wav_input)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 失敗した区間の失敗が 1 回届き、その後の区間が通し番号の順に届いている
        segments = segments_of(payloads)
        assert [segment["segment_number"] for segment in segments] == [1, 2, 3]
        assert [segment["result"] for segment in segments] == ["transcribed", "failed", "transcribed"]
        failed = segments[TROUBLED_SEGMENT - 1]
        assert failed["session_id"] == session_id
        assert failed["text"] == ""
        assert failed["error"]
        assert THREE_SENTENCES[0][1] in segments[0]["text"]
        assert THREE_SENTENCES[2][1] in segments[2]["text"]
        assert_completed(payloads, session_id, segment_count=len(THREE_SENTENCES))

    run_app(case, wav_input=wav_input, keys=KeyLog())


def test_error_when_segment_callback_unreachable(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """連続録音の区間の返送先に届かなくても、決めた回数まで再送してログに書き、次の区間と終わりを返す（異常シナリオ（区間の返送先に届かない））。"""
    # 準備: 通し番号 2 の区間の返送にだけ 500 を返し続け（1 回目と再送の全て）、再送の間隔を短くする
    monkeypatch.setattr(callback_service, "CALLBACK_RETRY_BASE_SEC", SHORT_RETRY_BASE_SEC)
    receiver.statuses = [200] + [500] * (1 + CALLBACK_RETRY_COUNT)
    wav_input = _three_sentences_input(tmp_path)

    def case(app: ResidentApp) -> None:
        """連続録音を始めて完了し、再送の回数・ログ・その後の区間を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        _finish_by_complete(app, session_id, wav_input)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 通し番号 2 の区間の返送が、1 回目と再送の回数だけ送られ、ログに書かれている
        sent_for_unreachable = [
            payload for payload in payloads if payload["segment_number"] == TROUBLED_SEGMENT
        ]
        assert len(sent_for_unreachable) == 1 + CALLBACK_RETRY_COUNT
        assert any(
            "返送先に届かなかった" in message
            and session_id in message
            and f"区間: {TROUBLED_SEGMENT}" in message
            for message in app.log_messages("ERROR")
        )

        # 検証: 通し番号 1 と 3 の区間と終わりが、この順に届いている（連続録音は止まっていない）
        delivered = [
            payload for payload in payloads if payload["segment_number"] != TROUBLED_SEGMENT
        ]
        segments = segments_of(delivered)
        assert [segment["segment_number"] for segment in segments] == [1, 3]
        assert THREE_SENTENCES[0][1] in segments[0]["text"]
        assert THREE_SENTENCES[2][1] in segments[1]["text"]
        assert_completed(delivered, session_id, segment_count=len(THREE_SENTENCES))
        assert len(delivered) == len(THREE_SENTENCES)

    run_app(case, wav_input=wav_input, keys=KeyLog())


def test_normal_when_enter_with_modifier(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """貼り付けて送信の修飾キーを Ctrl にすると、貼り付けのキーの後に、Ctrl を添えた Enter が送られる（正常シナリオ（Enter と一緒に修飾キーを押す））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「貼り付けて送信」で確定し、届け先と Enter に添えた修飾キーを確かめる。"""
        # 実行
        _record_and_confirm(app, "output_button_paste_and_send")
        app.wait_processed()

        # 検証
        assert SPEECH_WORD in pyperclip.paste()
        assert len(keys.pasted) == 1
        assert keys.enters == 1
        assert keys.enter_modifiers == [("ctrl",)]

    run_app(
        case,
        extra_settings=ENTER_WITH_CTRL_SETTINGS,
        wav_input=speech_input(tmp_path),
        keys=keys,
    )


def test_normal_when_copy_again_from_notification(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """コピーの完了の通知を押すと、ほかのアプリが上書きしていても、その通知のときに起こした文字をもう一度コピーする（正常シナリオ（コピーの完了の通知を押してもう一度コピーする））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「コピーのみ」で届け、クリップボードを上書きしてから通知を押し、クリップボードとログフォルダと貼り付けのキーを確かめる。"""
        # 準備: 「コピーのみ」で届け、コピーの完了の通知が出た後に、別の文字をクリップボードへコピーする
        _record_and_confirm(app, "output_button_copy_only")
        app.wait_processed()
        assert app.wait_until(lambda: app.notified("copy_completed"))
        QTest.qWait(300)
        transcript = pyperclip.paste()
        pyperclip.copy(OVERWRITTEN_TEXT)

        # 実行: 通知を押す
        app.click_notification()

        # 検証
        assert transcript == app.history_text()
        assert pyperclip.paste() == transcript
        assert app.opened_folders == []
        assert keys.pasted == []
        assert keys.enters == 0

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_switch_to_copy_only(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """文字起こし中の表示で「コピーのみ」へ切り替えると、今の出力先が替わり、起こした文字をコピーするだけで貼り付けも Enter も送らない（正常シナリオ（文字起こし中にコピーのみへ切り替える））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「貼り付けて送信」で確定し、文字起こし中に「コピーのみ」へ切り替え、届け先を確かめる。"""
        # 準備: 「貼り付けて送信」で確定する。今の出力先は「貼り付けて送信」
        _record_and_confirm(app, "output_button_paste_and_send")
        assert app.wait_until(lambda: _is_checked(app, "switch_button_paste_and_send"))
        assert app.label("paste_hint") == HINT_TEXT

        # 実行: 文字起こし中の表示で「コピーのみ」へ切り替える
        app.press("switch_button_copy_only")

        # 検証: 今の出力先が「コピーのみ」に変わっている
        assert app.wait_until(lambda: _is_checked(app, "switch_button_copy_only"))
        assert not _is_checked(app, "switch_button_paste_and_send")
        assert app.label("paste_hint") == COPY_HINT_TEXT
        app.wait_processed()

        # 検証: 起こした文字をコピーするだけで、キーは送られず、コピーの完了の通知が出ている
        assert pyperclip.paste() == app.history_text() != ""
        assert keys.pasted == []
        assert keys.enters == 0
        assert app.notified("copy_completed")

    run_app(case, wav_input=speech_input(tmp_path, repeat=SWITCH_REPEAT), keys=keys)


def test_normal_when_switch_to_paste_only(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """文字起こし中の表示で「貼り付けのみ」へ切り替えると、起こした文字を貼り付けるだけで Enter は送らず、コピーの完了の通知は出ない（正常シナリオ（文字起こし中に貼り付けのみへ切り替える））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """「コピーのみ」で確定し、文字起こし中に「貼り付けのみ」へ切り替え、届け先を確かめる。"""
        # 準備: 「コピーのみ」で確定する
        _record_and_confirm(app, "output_button_copy_only")
        assert app.wait_until(lambda: _is_checked(app, "switch_button_copy_only"))

        # 実行: 文字起こし中の表示で「貼り付けのみ」へ切り替える
        app.press("switch_button_paste_only")
        assert app.wait_until(lambda: _is_checked(app, "switch_button_paste_only"))
        app.wait_processed()

        # 検証: 起こした文字を貼り付けるだけで、Enter は送られず、コピーの完了の通知は出ていない
        assert pyperclip.paste() == app.history_text() != ""
        assert len(keys.pasted) == 1
        assert keys.enters == 0
        assert not app.notified("copy_completed")

    run_app(case, wav_input=speech_input(tmp_path, repeat=SWITCH_REPEAT), keys=keys)
