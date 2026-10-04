"""単一ユースケース「録音する」の E2E テスト。

本物の常駐アプリを起動し、トレイ・録音の画面を UI Automation で操作する（録音の始め方・話す音は、
複合ユースケース「声で入力した文字を貼り付ける」と同じ）。
実機のマイクで録音し、システム音量を一時的に下げる（`--run-e2e` が無ければ skip する）。

次の 2 つは、実機の環境を整えたときだけ動く（整っていなければ理由を出して skip する）。
- マイクの欠落: 録音の入力の音声デバイスを外し、環境変数 `VOICE_PASTE_E2E_NO_MICROPHONE=1` を指定する
- 複数のモニター: モニターが 2 枚以上つながっている
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import pyperclip
import pytest
from scipy.io import wavfile

from tests.integration.helpers import CallbackReceiver
from tests.support.app_driver import (
    CANCEL_HOTKEY,
    IDLE,
    PAUSE_HOTKEY,
    RECORDING,
    START_HOTKEY,
    AppDriver,
)
from tests.support.desktop import (
    NO_MICROPHONE_ENV,
    PASTE_TARGET_TITLE,
    Monitor,
    PasteTarget,
    drag,
    foreground_title,
    master_volume,
    monitors,
    move_cursor,
    press_hotkey,
    speak,
    wait_until,
    z_order,
)
from tests.support.flows import (
    NO_SPEECH_SETTINGS,
    PASTE_AND_SEND_BUTTON,
    PASTE_AND_SEND_ONLY,
    PASTE_TIMEOUT_SEC,
    SPEECH_TEXT,
    begin_recording,
    speak_and_confirm,
    wait_pasted,
    wait_processed,
    wait_volume_lowered,
    wait_volume_restored,
)

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

HALF_VOLUME_SETTINGS = "[recording]\nlower_volume = true\nvolume_percent = 50.0\n"
"""録音中にシステム音量を今の音量の半分へ下げる設定。"""

HIDE_WINDOW_RETRY_SEC = 1.5
"""録音の画面が出ていないことを確かめるために、録音を始めてから待つ秒数。"""

PAUSE_SEC = 3.0
"""一時停止したまま待つ秒数（この間に読み上げた声は録られない）。"""

ELAPSED_TOLERANCE_SEC = 2.0
"""経過時間の表示と実際の長さの許す差。"""

FOREGROUND_TIMEOUT_SEC = 5.0
"""前面が貼り付け先の窓に戻るのを待つ上限。"""


def _elapsed_seconds(text: str) -> int:
    """録音の画面の経過時間（mm:ss か h:mm:ss）を秒にする。"""
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def _wav_duration_sec(path: Path) -> float:
    """録音の WAV の長さ（秒）を返す。"""
    sample_rate, samples = wavfile.read(path)
    return float(len(samples)) / float(sample_rate)


def _paste_target_is_foreground() -> bool:
    """前面が貼り付け先の窓に戻る（または保たれる）まで待ち、戻ったかを返す。"""
    return wait_until(lambda: foreground_title() == PASTE_TARGET_TITLE, FOREGROUND_TIMEOUT_SEC)


def test_normal(start_app: StartApp, paste_target: PasteTarget) -> None:
    """録音中にシステム音量を半分へ下げ、録音の画面の「貼り付けて送信」で確定すると、録音が履歴に残り音量が戻って文字起こしへ進む（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + HALF_VOLUME_SETTINGS)
    volume_before = master_volume()

    # 実行
    begin_recording(app, paste_target)
    assert wait_volume_lowered(volume_before)
    volume_during = master_volume()
    speak_and_confirm(app)

    # 検証
    assert volume_before < 0.1 or volume_during == pytest.approx(volume_before * 0.5, abs=0.1)
    assert app.wait_window_gone("recording_window")
    assert wait_pasted(paste_target), "文字起こしへ進んでいない（スピーカーの音をマイクが拾えない環境ではないか）"
    wait_processed(app)
    assert len(app.service.history_files(".wav")) == 1
    assert wait_volume_restored(volume_before)


def test_normal_when_pause_and_resume(start_app: StartApp, paste_target: PasteTarget) -> None:
    """一時停止の間は経過時間が止まり、その間に読み上げた声は録られず、再開すると続きを録る（正常シナリオ）。"""
    # 準備（起こした文字は貼り付けず、録音の長さだけを見る）
    app = start_app(PASTE_AND_SEND_ONLY + NO_SPEECH_SETTINGS)
    started_at = time.monotonic()
    begin_recording(app, paste_target)
    speak("あいうえお")

    # 実行
    paused_at = time.monotonic()
    app.press("pause_button")
    app.wait_window("resume_button")
    paused_label = app.label("state_label")
    elapsed_when_paused = app.label("elapsed_label")
    speak(SPEECH_TEXT)
    time.sleep(PAUSE_SEC)
    elapsed_after_wait = app.label("elapsed_label")
    app.press("resume_button")
    paused_sec = time.monotonic() - paused_at
    time.sleep(1.0)
    elapsed_before_confirm = app.label("elapsed_label")
    wall_sec = time.monotonic() - started_at
    app.press(PASTE_AND_SEND_BUTTON)

    # 検証
    assert "一時停止中" in paused_label
    assert elapsed_when_paused == elapsed_after_wait
    expected_elapsed = wall_sec - paused_sec
    assert abs(_elapsed_seconds(elapsed_before_confirm) - expected_elapsed) <= ELAPSED_TOLERANCE_SEC
    assert app.wait_window_gone("recording_window")
    wait_processed(app)
    [recording] = app.service.history_files(".wav")
    assert _wav_duration_sec(recording) <= wall_sec - paused_sec + ELAPSED_TOLERANCE_SEC


@pytest.mark.parametrize("button", ["cancel_button", "close_button"], ids=["cancel", "close"])
def test_normal_when_cancel(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str, button: str
) -> None:
    """録音の画面の「取り消す」のボタンと閉じるボタン（×）で、録音を捨てて音量を戻し、前面を貼り付け先へ戻して、待機中に戻る（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + HALF_VOLUME_SETTINGS)
    volume_before = master_volume()
    begin_recording(app, paste_target)
    assert wait_volume_lowered(volume_before)

    # 実行
    app.press(button)

    # 検証
    assert app.wait_window_gone("recording_window")
    app.wait_tray_state(IDLE)
    assert app.service.history_files(".wav") == []
    assert pyperclip.paste() == clipboard_sentinel
    assert wait_volume_restored(volume_before)
    assert _paste_target_is_foreground()


def test_normal_when_hide_window(start_app: StartApp, receiver: CallbackReceiver) -> None:
    """API から始めた録音は、設定によらず録音の画面を出さず、トレイだけが録音中を示し、完了すると録音が履歴に残る（正常シナリオ）。"""
    # 準備
    app = start_app(HALF_VOLUME_SETTINGS)
    volume_before = master_volume()

    # 実行
    response, _elapsed_ms = app.service.start_session(receiver.url)
    assert response.status_code == 202
    session_id = str(response.json()["session_id"])
    app.wait_tray_state(RECORDING)
    time.sleep(HIDE_WINDOW_RETRY_SEC)

    # 検証（録音中）
    assert app.window("recording_window") is None
    assert wait_volume_lowered(volume_before)
    assert app.service.post(f"/sessions/{session_id}/stop").status_code == 200
    assert app.service.post(f"/sessions/{session_id}/complete").status_code == 202

    # 検証（完了後）
    assert wait_until(lambda: len(receiver.received) >= 1, PASTE_TIMEOUT_SEC)
    wait_processed(app)
    assert len(app.service.history_files(".wav")) == 1
    assert wait_volume_restored(volume_before)


def test_normal_when_history_off(start_app: StartApp, paste_target: PasteTarget) -> None:
    """履歴を残さない設定では、録音は一時の音声として保存して文字起こしへ進み、履歴には残らない（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + "[history]\nenabled = false\n")
    tmp_dir = app.service.data_dir / "tmp"
    begin_recording(app, paste_target)
    speak(SPEECH_TEXT)

    # 実行（確定してから処理が終わるまで、一時の音声が置かれるのを見る）
    app.press(PASTE_AND_SEND_BUTTON)
    seen_temporary = wait_until(lambda: any(tmp_dir.glob("*.wav")), 60)
    wait_processed(app)

    # 検証
    assert seen_temporary, "一時の音声が置かれなかった"
    assert app.service.history_files(".wav") == []
    assert list(tmp_dir.glob("*.wav")) == []


def test_error_when_busy(start_app: StartApp, receiver: CallbackReceiver) -> None:
    """API から始めた録音が録音中のときに録音開始のホットキーを押すと、処理中のダイアログで知らせ、録音は続く（異常シナリオ）。"""
    # 準備
    app = start_app()
    response, _elapsed_ms = app.service.start_session(receiver.url)
    assert response.status_code == 202
    app.wait_tray_state(RECORDING)

    # 実行
    press_hotkey(START_HOTKEY)

    # 検証
    app.wait_window("busy_dialog")
    assert "録音を始められません" in app.texts("busy_dialog")
    assert app.tray_state() == RECORDING
    assert app.window("recording_window") is None
    app.press("close_button")
    assert app.wait_window_gone("busy_dialog")


@pytest.fixture
def no_microphone_environment() -> None:
    """録音の入力の音声デバイスを外した環境でなければ、理由を出して skip する。"""
    if os.environ.get(NO_MICROPHONE_ENV) != "1":
        pytest.skip(
            f"録音の入力の音声デバイスを外した環境で、環境変数 {NO_MICROPHONE_ENV}=1 を指定したときだけ確かめる"
        )


@pytest.fixture
def two_monitors() -> tuple[Monitor, Monitor]:
    """主のモニターと、それ以外のモニター 1 枚を返す。モニターが 2 枚未満なら、理由を出して skip する。"""
    all_monitors = monitors()
    if len(all_monitors) < 2:
        pytest.skip(f"モニターが 2 枚以上つながっている環境でだけ確かめる（今は {len(all_monitors)} 枚）")
    primary = next(monitor for monitor in all_monitors if monitor.primary)
    secondary = next(monitor for monitor in all_monitors if not monitor.primary)
    return primary, secondary


def test_error_when_microphone_missing(start_app: StartApp, no_microphone_environment: None) -> None:
    """マイクを開けないと、録音の画面を出さず、音量を戻し、知らせて待機中に戻る（異常シナリオ）。録音の入力の音声デバイスを外した環境でだけ動く。"""
    # 準備
    app = start_app(HALF_VOLUME_SETTINGS)
    volume_before = master_volume()

    # 実行
    app.start_recording()

    # 検証
    assert wait_until(lambda: app.notified("microphone_unavailable"), 30)
    app.wait_tray_state(IDLE)
    assert app.window("recording_window") is None
    assert wait_volume_restored(volume_before)
    assert app.menu_item_enabled("menu_start")
    assert any(record["level"] == "ERROR" or record["level"] == "WARNING" for record in app.service.log_records())


# === 録音の画面の最前面・表示位置（#4・PoC で測れていない範囲） ===

CENTER_SETTINGS_PRIMARY = '[ui]\nfollow_cursor = false\nposition = "center"\n'
"""カーソルのあるモニターには出さず、主のモニターの中央に出す設定。"""

CENTER_SETTINGS_FOLLOW_CURSOR = '[ui]\nfollow_cursor = true\nposition = "center"\n'
"""カーソルのあるモニターの中央に出す設定。"""

FOCUS_SETTLE_SEC = 0.5
"""貼り付け先を前面に出してから、録音の画面との前後を見るまで待つ秒数。"""


def _focus_paste_target_and_check_order(paste_target: PasteTarget, recording_hwnd: int) -> None:
    """貼り付け先を前面に出し、録音の画面がその上にあることを確かめる。"""
    paste_target.focus()
    assert foreground_title() == PASTE_TARGET_TITLE
    assert z_order(recording_hwnd) < z_order(paste_target.hwnd())
    time.sleep(FOCUS_SETTLE_SEC)


def _start_on_monitor_and_cancel(app: AppDriver, monitor: Monitor) -> None:
    """モニターの中央にカーソルを置いて録音を始め、録音の画面がそのモニターの作業領域に出たら取り消す。"""
    move_cursor(*monitor.center())
    begin_recording(app)
    assert monitor.contains(app.uia.rect(app.wait_window("recording_window")))
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")
    app.wait_tray_state(IDLE)


def test_normal_when_other_window_focused(start_app: StartApp, paste_target: PasteTarget) -> None:
    """「常に手前に表示」でないほかの窓を前面に出しても、録音の画面はその上に残る（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app)
    recording_hwnd = app.recording_hwnd()

    # 実行・検証（貼り付け先を前面に出すたびに、録音の画面がその上にある）
    _focus_paste_target_and_check_order(paste_target, recording_hwnd)
    _focus_paste_target_and_check_order(paste_target, recording_hwnd)
    _focus_paste_target_and_check_order(paste_target, recording_hwnd)
    app.press("cancel_button")


def test_normal_when_primary_monitor(
    start_app: StartApp, two_monitors: tuple[Monitor, Monitor]
) -> None:
    """カーソルのあるモニターに出さない設定では、複数のモニターがあっても主のモニターの作業領域に出る（正常シナリオ）。"""
    # 準備
    primary, secondary = two_monitors
    app = start_app(CENTER_SETTINGS_PRIMARY)
    move_cursor(*secondary.center())

    # 実行
    begin_recording(app)

    # 検証
    assert primary.contains(app.uia.rect(app.wait_window("recording_window")))
    app.press("cancel_button")


def test_normal_when_follow_cursor(
    start_app: StartApp, two_monitors: tuple[Monitor, Monitor]
) -> None:
    """カーソルのあるモニターに出す設定では、カーソルのあるモニターの作業領域に出る（正常シナリオ）。"""
    # 準備
    primary, secondary = two_monitors
    app = start_app(CENTER_SETTINGS_FOLLOW_CURSOR)

    # 実行・検証（それぞれのモニターにカーソルを置いて録音を始める）
    _start_on_monitor_and_cancel(app, primary)
    _start_on_monitor_and_cancel(app, secondary)


# === 録音の画面を動かす・隠して戻す ===

MOVE_DISTANCE_PX = (200, 150)
"""録音の画面をドラッグで動かす距離（横・縦。物理ピクセル）。"""

MOVE_TOLERANCE_PX = 8
"""ドラッグで動いた距離と、動かした距離の許す差。"""

HIDDEN_SEC = 3.0
"""録音の画面を隠したまま話し続ける秒数。"""

START_HOTKEY_FREE_SETTINGS = '[[outputs]]\nid = "paste_and_send"\nhotkey = "<ctrl>+<alt>+s"\n'
"""録音開始のホットキーと同じホットキーの出力先を持たない設定（録音開始のホットキーで隠した画面を戻せる）。"""

RESTORE_MEANS = ["tray_icon", "tray_menu", "start_hotkey"]
"""隠した録音の画面を戻す手段。"""


def _shift_inside(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """録音の画面を MOVE_DISTANCE_PX だけ動かして作業領域に収まる向きを選び、動かす量（横・縦）を返す。"""
    work = next(monitor for monitor in monitors() if monitor.contains(rect)).work
    dx, dy = MOVE_DISTANCE_PX
    dx = -dx if rect[0] - dx >= work[0] and rect[2] + dx > work[2] else dx
    dy = -dy if rect[1] - dy >= work[1] and rect[3] + dy > work[3] else dy
    return dx, dy


def _restore_window(app: AppDriver, means: str) -> None:
    """隠した録音の画面を、手段（トレイのアイコンの左クリック・メニューの「録音の画面を出す」・録音開始のホットキー）で戻す。"""
    if means == "tray_icon":
        app.click_tray_icon()
    elif means == "tray_menu":
        app.choose_tray_menu("menu_show_window")
    else:
        press_hotkey(START_HOTKEY)
    app.wait_window("recording_window")


def _hide_window(app: AppDriver) -> None:
    """録音の画面の「隠す」を押し、画面が消えて、トレイが録音中のまま、前面が貼り付け先へ戻るのを確かめる。"""
    app.press("hide_button")
    assert app.wait_window_gone("recording_window")
    assert app.tray_state() == RECORDING
    assert _paste_target_is_foreground()


def test_normal_when_move_window(start_app: StartApp, paste_target: PasteTarget) -> None:
    """録音の画面の見出しの行をドラッグすると、放した位置へ動き、録音も経過時間も止まらず、動かした後も録音の画面のボタンで確定できる（正常シナリオ）。"""
    # 準備（起こした文字は貼り付けず、録音の長さだけを見る）
    app = start_app(PASTE_AND_SEND_ONLY + NO_SPEECH_SETTINGS)
    begin_recording(app, paste_target)
    before = app.recording_rect()
    elapsed_before = _elapsed_seconds(app.label("elapsed_label"))
    dx, dy = _shift_inside(before)
    grab = app.uia.center(app.wait_window("state_label"))

    # 実行
    drag(grab, (grab[0] + dx, grab[1] + dy))
    time.sleep(1.5)

    # 検証（位置と、録音が続いていること）
    after = app.recording_rect()
    assert abs(after[0] - before[0] - dx) <= MOVE_TOLERANCE_PX
    assert abs(after[1] - before[1] - dy) <= MOVE_TOLERANCE_PX
    assert _elapsed_seconds(app.label("elapsed_label")) > elapsed_before
    assert app.tray_state() == RECORDING

    # 実行・検証（動かした後も確定できる）
    speak_and_confirm(app)
    assert app.wait_window_gone("recording_window")
    wait_processed(app)
    assert len(app.service.history_files(".wav")) == 1


@pytest.mark.parametrize("means", RESTORE_MEANS)
@pytest.mark.parametrize("pause", [False, True], ids=["nothing", "pause"])
def test_normal_when_hide_and_restore(
    start_app: StartApp, paste_target: PasteTarget, pause: bool, means: str
) -> None:
    """録音の画面を隠しても録音は続き、戻すと隠していた間を含む経過時間と今の状態のまま、フォーカスを取らずに出る。隠している間に一時停止すると、戻した画面が一時停止中を示し、経過時間はそのとき止まっている（正常シナリオ）。"""
    # 準備（起こした文字は貼り付けず、録音の長さだけを見る）
    settings = START_HOTKEY_FREE_SETTINGS if means == "start_hotkey" else PASTE_AND_SEND_ONLY
    app = start_app(settings + NO_SPEECH_SETTINGS)
    started_at = time.monotonic()
    begin_recording(app, paste_target)

    # 実行（隠して、隠している間に話すか一時停止し、戻す）
    _hide_window(app)
    hidden_at = time.monotonic()
    if pause:
        press_hotkey(PAUSE_HOTKEY)
        paused_elapsed_sec = time.monotonic() - started_at
        time.sleep(HIDDEN_SEC)
    else:
        speak(SPEECH_TEXT)
        time.sleep(HIDDEN_SEC)
    hidden_sec = time.monotonic() - hidden_at
    _restore_window(app, means)
    wall_sec = time.monotonic() - started_at

    # 検証（戻した画面の経過時間・状態と、前面）
    elapsed_sec = _elapsed_seconds(app.label("elapsed_label"))
    if pause:
        assert "一時停止中" in app.label("state_label")
        assert abs(elapsed_sec - paused_elapsed_sec) <= ELAPSED_TOLERANCE_SEC
    else:
        assert "録音中" in app.label("state_label")
        assert abs(elapsed_sec - wall_sec) <= ELAPSED_TOLERANCE_SEC
    assert _paste_target_is_foreground()

    # 実行・検証（戻した後も確定でき、隠していた間に話した声が録られている）
    app.press(PASTE_AND_SEND_BUTTON)
    assert app.wait_window_gone("recording_window")
    wait_processed(app)
    [recording] = app.service.history_files(".wav")
    if not pause:
        assert _wav_duration_sec(recording) >= hidden_sec - ELAPSED_TOLERANCE_SEC


def test_normal_when_confirm_while_hidden(start_app: StartApp, paste_target: PasteTarget) -> None:
    """録音の画面を隠したまま確定のホットキー（貼り付けて送信）で確定でき、文字起こしへ進み、次の録音では録音の画面がいつもどおり出る（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app, paste_target)
    _hide_window(app)
    speak(SPEECH_TEXT)

    # 実行（既定の設定では、録音開始のホットキーが「貼り付けて送信」のホットキー）
    press_hotkey(START_HOTKEY)

    # 検証（確定して文字起こしへ進む）
    assert wait_pasted(paste_target), "文字起こしへ進んでいない（スピーカーの音をマイクが拾えない環境ではないか）"
    wait_processed(app)
    assert len(app.service.history_files(".wav")) == 1

    # 実行・検証（次の録音では録音の画面が出る）
    begin_recording(app, paste_target)
    assert app.window("recording_window") is not None
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")


def test_normal_when_cancel_while_hidden(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """録音の画面を隠したまま取り消しのホットキーで取り消すと、録音を捨てて待機中に戻り、次の録音では録音の画面がいつもどおり出る（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app, paste_target)
    _hide_window(app)

    # 実行
    press_hotkey(CANCEL_HOTKEY)

    # 検証（取り消されて文字起こしへ進まない）
    app.wait_tray_state(IDLE)
    assert app.service.history_files(".wav") == []
    assert pyperclip.paste() == clipboard_sentinel

    # 実行・検証（次の録音では録音の画面が出る）
    begin_recording(app, paste_target)
    assert app.window("recording_window") is not None
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")
    app.wait_tray_state(IDLE)
