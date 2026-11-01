"""単一ユースケース「録音する」の E2E テスト。

常駐アプリを pytest のプロセスの中で `main()` から起動し（`--data-dir` の一時フォルダ、Qt は offscreen）、
ホットキーが押された体で登録された関数を呼び、録音の画面・トレイは Qt のイベントで操作する。実機のマウス・キーボードは使わない。
録音の入力は 音声合成（Windows は SAPI、Linux は Open JTalk）で決めた文を書き出した WAV（か無音の WAV、マイクを開けない入力）に、
システム音量は呼ばれた値を控えるものに、貼り付けのキーは送信したキーを控えるものに差し替え、実機のマイクを開かず、システム音量を変えず、キーを送信しない。
文字起こしはローカルの Whisper（Windows は GPU、Linux は CPU）で、クリップボードは実物を使う（テストの後に元の文字へ戻す）。API から始める録音の返送先は、テストが 127.0.0.1 に立てる受信先。

「ほかの窓を前面に出す」「主のモニターに出す」「カーソルのあるモニターに出す」「録音の画面を動かす」は、Windows の窓の重なり・モニター・窓の移動を使い
offscreen の Qt では起こせないため置かない。前面の窓（Windows のフォアグラウンド）は確かめず、フォーカスを取らないことは Qt のアクティブな窓が録音の画面でないことで確かめる。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from tests.integration.helpers import CallbackReceiver
from tests.support.continuous import (
    SEGMENT_GAP_SEC,
    SHORT_GAP_SEC,
    THREE_SENTENCES,
    assert_all_words,
    assert_completed,
    assert_each_word,
    assert_numbered_in_order,
    segments_of,
    sentences_of,
    words_of,
)
from tests.support.inprocess import (
    LONG_READING,
    SPEECH_WORD,
    expected_lowered_ratios,
    expected_restored_volumes,
    KeyLog,
    WavInput,
    read_wav,
    silence_input,
    speech_input,
    speech_sequence_input,
    speech_timeline_input,
    spy_on_transcribed_audio,
)
from tests.support.resident_app import (
    CANCEL_HOTKEY,
    IDLE,
    PASTE_AND_SEND_HOTKEY,
    PAUSE_HOTKEY,
    RECORDING,
    ResidentApp,
    unavailable_microphone,
)
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.recording.segmenter import MAX_SEGMENT_SEC, SEGMENT_PAD_SEC
from voice_paste.features.session.types import SessionState
from voice_paste.shared.types import Entry

pytestmark = pytest.mark.real_machine

RunApp = Callable[..., ResidentApp]

LOWERED_RATIO = 0.5
"""設定の既定（録音中の音量 50%）で、録音前の音量に掛けて下げる割合。"""

RECORDING_TEXT = "● 録音中"
PAUSED_TEXT = "● 一時停止中"
"""録音の画面の状態の表示。"""

SENTENCE_GAP_SEC = 1.5
"""一時停止・隠すの間に文を話させるために、文と文の間に挟む無音の長さ。"""

POSITION_MARGIN_SEC = 0.3
"""文を読み終えた位置から、次の文を読み始めるまでの無音の中で操作するための余裕。"""

ELAPSED_TOLERANCE_SEC = 1.5
"""録音の画面の経過時間（1 秒刻み）と、テストが計った経過時間の食い違いの許容。"""

FEED_TIMEOUT_SEC = 60.0
"""実時間で流す録音の入力が、決めた位置まで音を渡すのを待つ上限。"""

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

HIDE_WINDOW_SETTINGS = "[recording]\nhide_window = true\n"
"""録音の画面も文字起こし中の表示も出さない設定。"""

NO_HISTORY_SETTINGS = "[history]\nenabled = false\n"
"""履歴を残さない設定。"""


def _clock_seconds(text: str) -> int:
    """録音の画面の経過時間の表示（`mm:ss` か `h:mm:ss`）を秒にする。"""
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * SECONDS_PER_MINUTE + int(part)
    return seconds


def _assert_elapsed(app: ResidentApp, expected_sec: float) -> None:
    """録音の画面の経過時間が、expected_sec とほぼ同じ長さを示していることを確かめる。"""
    shown = _clock_seconds(app.label("elapsed_label"))
    assert abs(shown - expected_sec) <= ELAPSED_TOLERANCE_SEC, f"経過時間 {shown} 秒（期待 {expected_sec:.1f} 秒）"


def _wait_fed(app: ResidentApp, wav_input: WavInput, position_sec: float) -> None:
    """実時間で流す録音の入力が、WAV の先頭から position_sec まで音を渡すのを待つ。"""
    assert app.wait_until(lambda: wav_input.fed_sec >= position_sec, FEED_TIMEOUT_SEC), (
        f"録音の入力が {position_sec:.1f} 秒まで音を渡さなかった"
    )


def _hide_recording_window(app: ResidentApp) -> None:
    """録音の画面の「隠す」を押し、録音の画面が消えても録音中のままであることを確かめる。"""
    app.press("hide_button")
    assert app.wait_window_gone("recording_window")
    assert app.tray_state() == RECORDING
    assert app.menu_item_enabled("menu_show_window")


def _assert_heard(app: ResidentApp, heard: tuple[str, ...], not_heard: tuple[str, ...]) -> None:
    """履歴に残った録音を起こした文字が、heard の言葉を全て含み、not_heard の言葉を含まないことを確かめる。"""
    text = app.history_text()
    for word in heard:
        assert word in text
    for word in not_heard:
        assert word not in text


def test_normal(run_app: RunApp, tmp_path: Path, clipboard_sentinel: str) -> None:
    """録音開始のホットキーで録音を始め、録音の画面で「貼り付けて送信」を選ぶと、録音が履歴に残り、音量が戻り、貼り付けて送信へ進む（正常シナリオ）。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """録音を始めて確定し、録音の画面・履歴・音量・届け先を確かめる。"""
        # 実行: 録音を始め、録音の画面で「貼り付けて送信」を選んで確定する
        app.start_recording()
        assert app.volume_log().lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)
        app.press("output_button_paste_and_send")

        # 検証
        assert app.wait_window_gone("recording_window")
        app.wait_processed()
        assert SPEECH_WORD in app.history_text()
        assert app.volume_log().restored == expected_restored_volumes()
        assert len(keys.pasted) == 1
        assert keys.enters == 1

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_pause_and_resume(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """一時停止の間に話した声は録音に入らず、経過時間は一時停止の間を除いた長さを示す（正常シナリオ（一時停止して再開する））。"""
    # 準備: 3 文を実時間で流す。2 文目を一時停止の間に話す
    wav_input = speech_timeline_input(
        tmp_path, [(sentence, SENTENCE_GAP_SEC) for sentence in sentences_of(THREE_SENTENCES)]
    )
    first_end, second_end, _third_end = wav_input.sentence_ends_sec
    heard = THREE_SENTENCES[0][1], THREE_SENTENCES[2][1]
    not_heard = (THREE_SENTENCES[1][1],)

    def case(app: ResidentApp) -> None:
        """1 文目を話し終えたら一時停止し、2 文目を話し終えたら再開して、確定する。"""
        # 準備
        app.start_recording()
        started = time.monotonic()
        _wait_fed(app, wav_input, first_end + POSITION_MARGIN_SEC)

        # 実行: 一時停止する。一時停止中を示し、経過時間が止まる
        app.press("pause_button")
        paused_at = time.monotonic()
        assert app.wait_until(lambda: app.label("state_label") == PAUSED_TEXT)
        frozen = app.label("elapsed_label")
        _wait_fed(app, wav_input, second_end + POSITION_MARGIN_SEC)
        assert app.label("elapsed_label") == frozen

        # 実行: 再開する。録音中を示す
        app.press("resume_button")
        resumed_at = time.monotonic()
        assert app.wait_until(lambda: app.label("state_label") == RECORDING_TEXT)
        app.wait_played_out(wav_input)
        QTest.qWait(200)

        # 検証: 経過時間が一時停止の間を除いた長さを示している
        _assert_elapsed(app, time.monotonic() - started - (resumed_at - paused_at))

        # 実行: 確定する
        app.press("output_button_paste_and_send")
        app.wait_processed()

        # 検証: 一時停止の間に話した声が入っていない
        _assert_heard(app, heard, not_heard)

    run_app(case, wav_input=wav_input, keys=KeyLog())


@pytest.mark.parametrize("button", ["cancel_button", "close_button"])
def test_normal_when_cancel(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
    button: str,
) -> None:
    """録音の画面の「取り消し」・閉じるボタン（×）で取り消すと、録音は残らず、音量が戻り、待機中に戻って文字起こしへ進まない（正常シナリオ（録音を取り消す））。"""
    # 準備
    transcribed = spy_on_transcribed_audio(monkeypatch)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """録音を始めて取り消し、録音の画面・履歴・音量・トレイを確かめる。"""
        # 準備
        app.start_recording()
        assert app.volume_log().lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)

        # 実行
        app.press(button)

        # 検証
        assert app.wait_window_gone("recording_window")
        assert app.wait_until(lambda: app.tray_state() == IDLE)
        QTest.qWait(500)
        assert app.history_files(".wav") == []
        assert app.volume_log().restored == expected_restored_volumes()
        assert app.current_session() is None
        assert transcribed == []
        assert keys.pasted == []

    run_app(case, wav_input=silence_input(tmp_path), keys=keys)


def _record_via_api(app: ResidentApp, receiver: CallbackReceiver) -> None:
    """API で録音を始め、録音の画面が出ていないことを確かめて、API の完了で確定する。"""
    session_id = app.start_api_session(receiver.url)
    assert app.wait_until(lambda: app.tray_state() == RECORDING)
    assert app.window("recording_window") is None
    app.complete_api_session(session_id)


def _record_via_hotkey(app: ResidentApp, receiver: CallbackReceiver) -> None:
    """録音の画面を出さない設定で録音開始のホットキーを押し、録音の画面が出ていないことを確かめて、確定のホットキーで確定する。"""
    app.press_start_hotkey()
    assert app.wait_until(lambda: app.tray_state() == RECORDING)
    assert app.window("recording_window") is None
    app.press_registered_hotkey(PASTE_AND_SEND_HOTKEY)


@pytest.mark.parametrize(
    ("record", "extra_settings"),
    [
        pytest.param(_record_via_api, "", id="api"),
        pytest.param(_record_via_hotkey, HIDE_WINDOW_SETTINGS, id="hotkey"),
    ],
)
def test_normal_when_no_window(
    run_app: RunApp,
    tmp_path: Path,
    receiver: CallbackReceiver,
    clipboard_sentinel: str,
    record: Callable[[ResidentApp, CallbackReceiver], None],
    extra_settings: str,
) -> None:
    """API から始めた録音と、画面を出さない設定でホットキーから始めた録音は、録音の画面を出さずに確定でき、履歴に残って文字起こしへ進む（正常シナリオ（録音の画面を出さない））。"""

    def case(app: ResidentApp) -> None:
        """録音の画面を出さずに録音を始めて確定し、履歴・音量・文字起こしを確かめる。"""
        # 実行
        record(app, receiver)
        app.wait_processed()

        # 検証
        assert SPEECH_WORD in app.history_text()
        assert app.volume_log().lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)
        assert app.volume_log().restored == expected_restored_volumes()
        assert app.window("recording_window") is None
        assert app.window("transcribing_indicator") is None

    run_app(case, extra_settings=extra_settings, wav_input=speech_input(tmp_path), keys=KeyLog())


def test_normal_when_no_history(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """履歴を残さない設定では、確定した録音は履歴に残らず一時の音声として文字起こしへ進み、終わると消える（正常シナリオ（履歴を残さない））。"""
    # 準備
    transcribed = spy_on_transcribed_audio(monkeypatch)
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """録音を確定し、履歴・一時の音声・文字起こしを確かめる。"""
        # 実行
        app.start_recording()
        app.press("output_button_paste_and_send")
        app.wait_processed()

        # 検証: 履歴に残らず、一時の音声が文字起こしに渡り、終わると消える
        assert app.history_files(".wav") == []
        assert app.history_files(".txt") == []
        [audio] = transcribed
        assert audio.existed
        assert audio.path.is_relative_to(app.data_dir / "tmp")
        assert not audio.path.exists()
        assert len(keys.pasted) == 1

    run_app(case, extra_settings=NO_HISTORY_SETTINGS, wav_input=speech_input(tmp_path), keys=keys)


def test_error_when_busy(run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver) -> None:
    """API から始めた録音の処理中に録音開始のホットキーを押すと、始められない理由がダイアログで知らされ、処理中の録音は続く（異常シナリオ（処理中に開始が来る））。"""
    # 準備: 無音の WAV を実時間で流す
    wav_input = silence_input(tmp_path, realtime=True)

    def case(app: ResidentApp) -> None:
        """API の録音の最中にホットキーを押し、ダイアログ・2 つ目の録音・処理中の録音を確かめる。"""
        # 準備
        session_id = app.start_api_session(receiver.url)
        assert app.wait_until(lambda: app.tray_state() == RECORDING)

        # 実行: 録音開始のホットキーを押し、出たダイアログを閉じる
        with app.answering("busy_dialog", "close_button") as answered:
            app.press_start_hotkey()
            assert app.wait_until(lambda: answered)

        # 検証: 2 つ目の録音が始まらず、処理中の録音が録音中のまま続いている
        assert app.notified_count("busy") == 1
        assert app.unexpected_dialogs == []
        assert wav_input.open_count == 1
        session = app.current_session()
        assert session is not None
        assert session.id == session_id
        assert session.entry == Entry.API
        assert session.state == SessionState.RECORDING
        assert app.window("recording_window") is None

        # 後始末: 処理中の録音を確定して終える
        app.complete_api_session(session_id)
        app.wait_processed()

    run_app(case, wav_input=wav_input)


def test_error_when_microphone_unavailable(run_app: RunApp) -> None:
    """マイクを開けないと、録音の画面は開かず、音量が戻り、待機中のままログに理由が書かれ、録音開始のホットキーをもう一度受け付ける（異常シナリオ（マイクを開けない））。"""

    def case(app: ResidentApp) -> None:
        """録音開始のホットキーを 2 回押し、録音の画面・音量・トレイ・ログ・受付を確かめる。"""
        # 実行
        app.press_start_hotkey()
        QTest.qWait(500)

        # 検証
        assert app.window("recording_window") is None
        assert app.volume_log().lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)
        assert app.volume_log().restored == expected_restored_volumes()
        assert app.tray_state() == IDLE
        assert app.current_session() is None
        assert app.notified_count("microphone_unavailable") == 1
        assert any(
            message.startswith("マイクを開けなかった（") for message in app.log_messages("ERROR")
        )

        # 実行: もう一度押す
        app.press_start_hotkey()
        QTest.qWait(500)

        # 検証: 処理中ではなく、もう一度受け付けてマイクを開こうとした
        assert app.notified_count("microphone_unavailable") == 2
        assert app.notified_count("busy") == 0

    run_app(case, wav_input=unavailable_microphone)


def _do_nothing(app: ResidentApp) -> None:
    """録音の画面を隠している間に、何もしない。"""


def _pause_by_hotkey(app: ResidentApp) -> None:
    """録音の画面を隠している間に、一時停止のホットキーで一時停止する。"""
    app.press_registered_hotkey(PAUSE_HOTKEY)


def _restore_by_tray_icon(app: ResidentApp) -> None:
    """隠した録音の画面を、トレイのアイコンの左クリックで戻す。"""
    app.click_tray_icon()


def _restore_by_tray_menu(app: ResidentApp) -> None:
    """隠した録音の画面を、トレイのメニューの「録音の画面を表示」で戻す。"""
    app.choose_tray_menu("menu_show_window")


def _restore_by_start_hotkey(app: ResidentApp) -> None:
    """隠した録音の画面を、録音開始のホットキーで戻す。"""
    app.press_start_hotkey()


@dataclass(frozen=True)
class HiddenOperation:
    """録音の画面を隠している間に行う操作と、戻した録音の画面と履歴の期待値。"""

    act: Callable[[ResidentApp], None]
    """隠している間に行う操作。"""

    state_text: str
    """戻した録音の画面の状態の表示。"""

    clock_stops: bool
    """操作で経過時間が止まるか。"""

    heard: tuple[str, ...]
    """履歴の録音を起こした文字に含まれるはずの言葉。"""

    not_heard: tuple[str, ...]
    """履歴の録音を起こした文字に含まれないはずの言葉。"""

    def reference_time(self, operated_at: float, now: float) -> float:
        """経過時間が数えている時刻を返す。操作で止まったなら操作した時刻、止まっていないなら今。"""
        return operated_at if self.clock_stops else now


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            HiddenOperation(
                act=_do_nothing,
                state_text=RECORDING_TEXT,
                clock_stops=False,
                heard=tuple(words_of(THREE_SENTENCES)),
                not_heard=(),
            ),
            id="nothing",
        ),
        pytest.param(
            HiddenOperation(
                act=_pause_by_hotkey,
                state_text=PAUSED_TEXT,
                clock_stops=True,
                heard=(THREE_SENTENCES[0][1],),
                not_heard=(THREE_SENTENCES[1][1], THREE_SENTENCES[2][1]),
            ),
            id="pause",
        ),
    ],
)
@pytest.mark.parametrize(
    "restore",
    [
        pytest.param(_restore_by_tray_icon, id="tray_icon"),
        pytest.param(_restore_by_tray_menu, id="tray_menu"),
        pytest.param(_restore_by_start_hotkey, id="start_hotkey"),
    ],
)
def test_normal_when_hide_and_restore(
    run_app: RunApp,
    tmp_path: Path,
    clipboard_sentinel: str,
    operation: HiddenOperation,
    restore: Callable[[ResidentApp], None],
) -> None:
    """録音の画面を隠しても録音は続き、戻した録音の画面は隠していた間を含む経過時間と今の状態を示し、フォーカスを取らない（正常シナリオ（録音の画面を隠して戻す））。"""
    # 準備: 3 文を実時間で流す。2 文目を録音の画面を隠している間に話す
    wav_input = speech_timeline_input(
        tmp_path, [(sentence, SENTENCE_GAP_SEC) for sentence in sentences_of(THREE_SENTENCES)]
    )
    first_end, second_end, _third_end = wav_input.sentence_ends_sec

    def case(app: ResidentApp) -> None:
        """1 文目を話し終えたら隠し、2 文目を話し終えたら戻して、確定する。"""
        # 準備
        app.start_recording()
        started = time.monotonic()
        _wait_fed(app, wav_input, first_end + POSITION_MARGIN_SEC)

        # 実行: 録音の画面を隠し、隠している間に操作する
        _hide_recording_window(app)
        operation.act(app)
        operated_at = time.monotonic()
        _wait_fed(app, wav_input, second_end + POSITION_MARGIN_SEC)

        # 検証: 隠している間、録音の画面が出ておらず、トレイのアイコンが録音中のまま
        assert app.window("recording_window") is None
        assert app.tray_state() == RECORDING

        # 実行: 録音の画面を戻す
        restore(app)
        restored_window = app.wait_widget("recording_window", QWidget)

        # 検証: 隠していた間を含む経過時間と今の状態を示し、フォーカスを取らない
        assert app.label("state_label") == operation.state_text
        _assert_elapsed(app, operation.reference_time(operated_at, time.monotonic()) - started)
        assert QApplication.activeWindow() is not restored_window
        assert not app.menu_item_enabled("menu_show_window")
        QTest.qWait(1000)
        _assert_elapsed(app, operation.reference_time(operated_at, time.monotonic()) - started)

        # 実行: 確定する
        app.wait_played_out(wav_input)
        app.press("output_button_paste_and_send")
        app.wait_processed()

        # 検証: 隠していた間に話した声が、一時停止していなければ録音に入っている
        _assert_heard(app, operation.heard, operation.not_heard)

    run_app(case, wav_input=wav_input, keys=KeyLog())


def test_normal_when_confirm_while_hidden(
    run_app: RunApp, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """録音の画面を隠したまま確定のホットキーで確定でき、次の録音では録音の画面がいつもどおり出る（正常シナリオ（隠したまま確定する））。"""
    # 準備
    keys = KeyLog()

    def case(app: ResidentApp) -> None:
        """録音の画面を隠して確定し、次の録音の録音の画面を確かめる。"""
        # 実行: 録音の画面を隠し、戻さずに確定のホットキーで確定する
        app.start_recording()
        _hide_recording_window(app)
        app.press_registered_hotkey(PASTE_AND_SEND_HOTKEY)
        app.wait_processed()

        # 検証: 選んだ出力先で文字起こしへ進んだ
        assert SPEECH_WORD in app.history_text()
        assert len(keys.pasted) == 1

        # 検証: 次の録音では録音の画面がいつもどおり出ている
        app.start_recording()
        app.press("cancel_button")
        assert app.wait_until(lambda: app.tray_state() == IDLE)

    run_app(case, wav_input=speech_input(tmp_path), keys=keys)


def test_normal_when_cancel_while_hidden(
    run_app: RunApp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """録音の画面を隠したまま取り消しのホットキーで取り消せ、次の録音では録音の画面がいつもどおり出る（正常シナリオ（隠したまま取り消す））。"""
    # 準備
    transcribed = spy_on_transcribed_audio(monkeypatch)

    def case(app: ResidentApp) -> None:
        """録音の画面を隠して取り消し、履歴・トレイと、次の録音の録音の画面を確かめる。"""
        # 実行: 録音の画面を隠し、戻さずに取り消しのホットキーで取り消す
        app.start_recording()
        _hide_recording_window(app)
        app.press_registered_hotkey(CANCEL_HOTKEY)

        # 検証: 録音は残らず、文字起こしへ進まず、トレイが待機中に戻っている
        assert app.wait_until(lambda: app.tray_state() == IDLE)
        QTest.qWait(500)
        assert app.history_files(".wav") == []
        assert transcribed == []

        # 検証: 次の録音では録音の画面がいつもどおり出ている
        app.start_recording()
        app.press("cancel_button")
        assert app.wait_until(lambda: app.tray_state() == IDLE)

    run_app(case, wav_input=silence_input(tmp_path), keys=KeyLog())


def _duration_sec(wav_path: Path) -> float:
    """WAV の録音の長さ（秒）を返す。"""
    return len(read_wav(wav_path)) / SAMPLE_RATE


def test_normal_when_split_by_silence(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """連続録音は、録音を止めずに文ごとの無音で区切って履歴に残し、区切った区間を通し番号の順に起こす（正常シナリオ（録音を停止せずに無音で区切る））。"""
    # 準備: 文の間に区切りの無音より長い無音を挟んだ WAV を実時間で流す
    wav_input = speech_sequence_input(
        tmp_path, sentences_of(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
    )

    def case(app: ResidentApp) -> None:
        """連続録音を始め、話し終えたら完了して、区間・履歴・音量を確かめる。"""
        # 実行: 連続録音を始め、話し終えたら完了する（最後の文を話し終えて無音が区切りの長さに届く前に完了する）
        session_id = app.start_api_session(receiver.url, continuous=True)
        assert app.wait_until(lambda: app.tray_state() == RECORDING)
        assert app.window("recording_window") is None
        assert app.volume_log().lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)
        app.wait_played_out(wav_input)
        app.complete_api_session(session_id)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 話した文ごとに区間が切り出され、通し番号の順に届いている（無音だけの間は区間にならない）
        segments = segments_of(payloads)
        assert_numbered_in_order(segments, session_id)
        assert_each_word(segments, words_of(THREE_SENTENCES))
        assert_completed(payloads, session_id, segment_count=len(THREE_SENTENCES))
        assert len(payloads) == len(THREE_SENTENCES) + 1
        recordings = app.segment_recordings()
        assert len(recordings) == len(segments)
        for recording, segment in zip(recordings, segments, strict=True):
            assert session_id in recording.name
            assert recording.with_suffix(".txt").read_text(encoding="utf-8") == segment["text"]
        assert app.volume_log().restored == expected_restored_volumes()

    run_app(case, wav_input=wav_input, keys=KeyLog())


def test_normal_when_split_by_max_length(
    run_app: RunApp, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """連続録音は、無音が来ないまま話し続けても区間の最大の長さで区切り、話した声を落とさずに起こす（正常シナリオ（話し続けて最大の長さで区切る））。"""
    # 準備: 区切りの無音に届かない間だけで、区間の最大の長さを超えて読み上げ続ける
    wav_input = speech_sequence_input(
        tmp_path, sentences_of(LONG_READING), gap_sec=SHORT_GAP_SEC
    )
    assert wav_input.duration_sec > MAX_SEGMENT_SEC

    def case(app: ResidentApp) -> None:
        """連続録音を始め、話し終えたら完了して、区間の長さと話した声を確かめる。"""
        # 実行
        session_id = app.start_api_session(receiver.url, continuous=True)
        app.wait_played_out(wav_input)
        app.complete_api_session(session_id)
        payloads = app.wait_for_continuous_end(receiver)
        app.wait_processed()

        # 検証: 区間が 2 つ以上に切れ、どれも最大の長さに余白を加えた長さ以下で、話した声が落ちていない
        segments = segments_of(payloads)
        assert len(segments) >= 2
        assert_numbered_in_order(segments, session_id)
        for recording in app.segment_recordings():
            assert _duration_sec(recording) <= MAX_SEGMENT_SEC + SEGMENT_PAD_SEC
        assert_all_words(segments, words_of(LONG_READING))
        assert_completed(payloads, session_id, segment_count=len(segments))

    run_app(case, wav_input=wav_input, keys=KeyLog())
