"""features/session/service.py（SessionManager の start・pause・stop・complete・cancel・truncate_if_expired・_run_after_confirm・switch_output・close・連続録音の _on_segment・_run_segments・_on_continuous_failed）の単体テスト。

SessionDeps の関数は全て Mock に差し替える。
ワーカースレッドは、起動を覚えるだけの偽物（defer_workers）に差し替えて、テストが動かすタイミングを決める。
連続録音のワーカースレッドは本物を動かし、区間の返送が届くのを待って確かめる。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.unit.voice_paste.features.session.helpers import (
    CALLBACK_URL,
    CONTINUOUS_LIMIT,
    LIMIT,
    START,
    Harness,
    defer_workers,
    make_harness,
    make_segment,
)
from voice_paste.shared.errors import (
    MicrophoneUnavailableError,
    SessionBusyError,
    SessionNotFoundError,
    TranscriptionError,
    UnknownOutputError,
)

if TYPE_CHECKING:
    from voice_paste.features.session.types import Session
    from voice_paste.shared.types import TranscriptionOutcome

WAIT_SEC = 2.0
CLOSE_LIMIT_SEC = 5.0
EARLY_TRUNCATE = timedelta(seconds=601)


@pytest.fixture
def audio_path(tmp_path: Path) -> Path:
    """save_recording が返す録音のパスを返す。"""
    return tmp_path / "20261001120000_s1.wav"


@pytest.fixture
def continuous_harness(audio_path: Path) -> Iterator[Harness]:
    """連続録音のワーカースレッドを本物で動かす Harness を返す。テストの後に終了で片付け、ワーカースレッドを残さない。"""
    h = make_harness(audio_path)
    yield h
    h.manager.close()


def _confirm_hotkey(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """ホットキーの録音セッションを始めて確定し、文字起こしから届けるまでは動かさずに止めておく。"""
    defer_workers(monkeypatch)
    h.manager.start("hotkey")
    h.manager.complete()


def _confirm_api(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """API の録音セッションを始めて確定し、文字起こしから届けるまでは動かさずに止めておく。"""
    defer_workers(monkeypatch)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.complete(session.id)


def _block_until_released(
    mock: MagicMock, result: object = None
) -> tuple[threading.Event, threading.Event]:
    """mock が呼ばれたら止まり、解放の合図が立つまで result を返さないようにする。呼ばれて止まった合図と、解放の合図を返す。"""
    entered = threading.Event()
    release = threading.Event()

    def _blocking(*_args: object) -> object:
        entered.set()
        release.wait(timeout=WAIT_SEC * 5)
        return result

    mock.side_effect = _blocking
    return entered, release


# === start ===


def test_start_when_idle(audio_path: Path) -> None:
    """待機中なら録音を始める（正常系）。"""
    # 準備
    h = make_harness(audio_path)

    # 実行
    session = h.manager.start("hotkey")

    # 検証
    assert str(session.state) == "recording"
    h.start_recording.assert_called_once()
    assert "state_changed" in h.events()


def test_start_when_busy(audio_path: Path) -> None:
    """処理中は断る（異常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行・検証
    with pytest.raises(SessionBusyError):
        h.manager.start("api", callback_url=CALLBACK_URL)
    h.start_recording.assert_called_once()


def test_start_when_microphone_unavailable(audio_path: Path) -> None:
    """マイクを開けなければ待機中のまま（異常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.start_recording.side_effect = [MicrophoneUnavailableError("マイクを開けない"), None]

    # 実行・検証
    with pytest.raises(MicrophoneUnavailableError):
        h.manager.start("hotkey")
    assert h.state() is None
    session = h.manager.start("hotkey")
    assert str(session.state) == "recording"


# === pause ===


def test_pause_when_recording(audio_path: Path) -> None:
    """録音中なら一時停止する（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行
    h.manager.pause()

    # 検証
    assert h.state() == "paused"
    h.pause_recording.assert_called_once()


def test_pause_when_api_session(audio_path: Path) -> None:
    """API の録音セッションに一時停止のホットキーが来ても変えない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager.pause()

    # 検証
    h.pause_recording.assert_not_called()
    assert h.state() == "recording"


# === stop ===


def test_stop_when_recording(audio_path: Path) -> None:
    """録音中なら止める（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager.stop(session.id)

    # 検証
    assert h.state() == "stopped"
    h.stop_recording.assert_called_once()


def test_stop_when_already_stopped(audio_path: Path) -> None:
    """止めた録音セッションは何も変えない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.stop(session.id)

    # 実行
    h.manager.stop(session.id)

    # 検証
    h.stop_recording.assert_called_once()
    assert h.state() == "stopped"


@pytest.mark.parametrize(
    "prepare",
    [
        pytest.param(lambda h: None, id="no_session"),
        pytest.param(lambda h: h.manager.start("api", callback_url=CALLBACK_URL), id="other_id"),
    ],
)
def test_stop_when_session_unknown(
    audio_path: Path, prepare: Callable[[Harness], object]
) -> None:
    """知らない ID は断る（異常系）。"""
    # 準備
    h = make_harness(audio_path)
    prepare(h)

    # 実行・検証
    with pytest.raises(SessionNotFoundError):
        h.manager.stop("unknown-session-id")


# === complete ===


def test_complete_when_stopped(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """止めた録音を確定する（正常系）。"""
    # 準備
    defer_workers(monkeypatch)
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.stop(session.id)
    stop_calls_before = h.stop_recording.call_count

    # 実行
    h.manager.complete(session.id)

    # 検証
    h.save_recording.assert_called_once()
    assert h.stop_recording.call_count == stop_calls_before
    assert h.state() == "transcribing"


def test_complete_when_recording(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """録音中なら止めてから確定する（正常系）。"""
    # 準備
    defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行
    h.manager.complete()

    # 検証
    names = h.call_names()
    assert names.index("stop_recording") < names.index("save_recording")


def test_complete_when_preset(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """選んだプリセットを、届けるときの Session に持たせる（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    preset = BrowserPreset(title="ChatGPT", url="https://chatgpt.com")

    # 実行
    h.manager.complete(preset=preset)
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    delivered_session = h.deliver.call_args.args[0]
    assert delivered_session.output_id is None
    assert delivered_session.output_preset == preset


def test_complete_when_hotkey_on_api_session(audio_path: Path) -> None:
    """API の録音セッションにホットキーの確定が来ても変えない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager.complete()

    # 検証
    h.stop_recording.assert_not_called()
    h.save_recording.assert_not_called()
    assert h.state() == "recording"


def test_complete_when_session_id_mismatch(audio_path: Path) -> None:
    """ID が違えば断る（異常系）。"""
    # 準備
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.stop(session.id)

    # 実行・検証
    with pytest.raises(SessionNotFoundError):
        h.manager.complete("other-session-id")
    h.save_recording.assert_not_called()


def test_complete_when_session_unknown(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """完了済みの録音セッションは断る（異常系）。"""
    # 準備
    defer_workers(monkeypatch)
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.complete(session.id)

    # 実行・検証
    with pytest.raises(SessionNotFoundError):
        h.manager.complete(session.id)


def test_complete_when_save_failed(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """録音を保存できなければ待機中に戻して呼び出し元へ failed を届ける（異常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.save_recording.side_effect = OSError("録音を保存できない")
    session = h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行・検証
    with pytest.raises(OSError, match="録音を保存できない"):
        h.manager.complete(session.id)
    assert h.state() is None
    started[0].run_now()
    assert h.delivered().result == "failed"
    assert str(h.manager.start("hotkey").state) == "recording"


def test_complete_when_save_failed_from_hotkey(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ホットキーの録音を保存できなければ待機中に戻して知らせる（異常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.save_recording.side_effect = OSError("録音を保存できない")
    h.manager.start("hotkey")

    # 実行・検証
    with pytest.raises(OSError, match="録音を保存できない"):
        h.manager.complete()
    assert h.state() is None
    started[0].run_now()
    assert "transcription_failed" in h.events()
    h.deliver.assert_not_called()
    assert str(h.manager.start("hotkey").state) == "recording"


# === cancel・_cancel・_expire_cancel ===


def test_cancel_returns_without_waiting(audio_path: Path) -> None:
    """取り消しの終わりを待たずに戻る（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._lock.acquire()

    # 実行
    h.manager.cancel()
    returned_while_locked = h.state() == "recording"
    h.manager._lock.release()

    # 検証
    assert returned_while_locked
    assert h.wait_for(lambda: h.state() == "cancel_pending")


def test_cancel_within_grace(audio_path: Path) -> None:
    """猶予の間の取り消しは画面だけを待機中にして猶予の終わりを予約する（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.clock.current = START + timedelta(seconds=1)

    # 実行
    h.manager._cancel()

    # 検証
    assert h.state() == "cancel_pending"
    h.restore_recording_volume.assert_called_once()
    assert h.start_cancel_timer.call_args.args[0] == 4.0
    h.discard_recording.assert_not_called()
    assert h.notify.call_args_list[-1].args == ("state_changed", "cancel_pending")


def test_cancel_after_grace(audio_path: Path) -> None:
    """猶予の後の取り消しはその場で捨てる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.clock.current = START + timedelta(seconds=6)

    # 実行
    h.manager._cancel()

    # 検証
    h.discard_recording.assert_called_once()
    assert h.state() is None
    h.start_cancel_timer.assert_not_called()


def test_cancel_when_grace_zero(audio_path: Path) -> None:
    """猶予が 0 ならその場で捨てる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.get_cancel_grace.return_value = timedelta(0)
    h.manager.start("hotkey")

    # 実行
    h.manager._cancel()

    # 検証
    h.discard_recording.assert_called_once()
    h.start_cancel_timer.assert_not_called()


def test_cancel_when_api_session(audio_path: Path) -> None:
    """API の録音セッションに取り消しのホットキーが来ても変えない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager._cancel()

    # 検証
    h.discard_recording.assert_not_called()
    assert h.state() == "recording"


def test_expire_cancel_when_pending(audio_path: Path) -> None:
    """猶予が終わったら捨てる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    h.fire_cancel_timer()

    # 検証
    h.discard_recording.assert_called_once()
    assert h.state() is None
    assert h.notify.call_args_list[-1].args == ("state_changed", "idle")


def test_expire_cancel_after_restart(audio_path: Path) -> None:
    """始め直した後の古いタイマーでは捨てない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()
    h.manager.start("hotkey")

    # 実行
    h.fire_cancel_timer()

    # 検証
    h.discard_recording.assert_not_called()
    assert h.state() == "recording"


def test_expire_cancel_after_recancel(audio_path: Path) -> None:
    """始め直した後にもう一度取り消したとき、古いタイマーでは捨てない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()
    h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    h.fire_cancel_timer(0)

    # 検証
    h.discard_recording.assert_not_called()
    assert h.state() == "cancel_pending"


# === 猶予中の録音セッションへの操作 ===


def test_start_when_cancel_pending(audio_path: Path) -> None:
    """猶予の間の開始は内部の録音を引き継いで始め直す（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    first = h.manager.start("hotkey")
    h.manager._cancel()
    h.clock.current = START + timedelta(seconds=2)

    # 実行
    session = h.manager.start("tray")

    # 検証
    assert session.id == first.id
    assert str(session.state) == "recording"
    assert str(session.entry) == "tray"
    assert session.started_at == START + timedelta(seconds=2)
    h.start_recording.assert_called_once()
    h.clear_recording.assert_called_once()
    h.lower_recording_volume.assert_called_once()
    h.cancel_timer.assert_called_once()


def test_start_api_when_cancel_pending(audio_path: Path) -> None:
    """猶予の間の API の開始は内部の録音を捨ててから始める（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    first = h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    session = h.manager.start("api", callback_url=CALLBACK_URL)

    # 検証
    assert session.id != first.id
    assert str(session.entry) == "api"
    h.discard_recording.assert_called_once()
    h.cancel_timer.assert_called_once()
    assert h.call_names()[-3:-1] == ["discard_recording", "start_recording"]


def test_complete_when_cancel_pending(audio_path: Path) -> None:
    """猶予中の録音は確定しない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    h.manager.complete(output_id="paste_and_send")

    # 検証
    h.stop_recording.assert_not_called()
    h.save_recording.assert_not_called()
    assert h.state() == "cancel_pending"


def test_pause_when_cancel_pending(audio_path: Path) -> None:
    """猶予中の録音は一時停止しない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    h.manager.pause()

    # 検証
    h.pause_recording.assert_not_called()
    assert h.state() == "cancel_pending"


def test_close_when_cancel_pending(audio_path: Path) -> None:
    """猶予中の録音は猶予を待たずに捨てる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.manager._cancel()

    # 実行
    h.manager.close()

    # 検証
    h.discard_recording.assert_called_once()
    h.cancel_timer.assert_called_once()
    assert h.state() is None


# === truncate_if_expired ===


def test_truncate_if_expired_when_recording(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """録音中のまま上限を過ぎたら打ち切る（正常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)
    h.clock.current = START + LIMIT

    # 実行
    truncated = h.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    h.stop_recording.assert_called_once()
    h.save_recording.assert_called_once()
    assert h.state() == "delivering"
    assert len(started) == 1
    h.deliver.assert_not_called()


def test_truncate_if_expired_when_worker_runs(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ワーカースレッドが打ち切りを届けて片付ける（正常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)
    h.clock.current = START + LIMIT
    h.manager.truncate_if_expired()

    # 実行
    started[0].run_now()

    # 検証
    assert h.delivered().result == "truncated"
    h.discard_temporary.assert_called_once_with(audio_path)
    assert h.state() is None


def test_truncate_if_expired_when_deliver_blocks(audio_path: Path) -> None:
    """返送を待つ間も開始はすぐ 409 になる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    deliver_entered = threading.Event()
    release_deliver = threading.Event()

    def _blocking_deliver(*_args: object) -> None:
        deliver_entered.set()
        release_deliver.wait(timeout=WAIT_SEC * 5)

    h.deliver.side_effect = _blocking_deliver
    h.manager.start("api", callback_url=CALLBACK_URL)
    h.clock.current = START + LIMIT
    h.manager.truncate_if_expired()
    assert deliver_entered.wait(timeout=WAIT_SEC)
    start_errors: list[Exception] = []

    def _start_from_other_thread() -> None:
        try:
            h.manager.start("hotkey")
        except SessionBusyError as error:
            start_errors.append(error)

    other = threading.Thread(target=_start_from_other_thread)

    # 実行
    other.start()
    other.join(timeout=WAIT_SEC)

    # 検証
    release_deliver.set()
    assert not other.is_alive()
    assert len(start_errors) == 1


def test_truncate_if_expired_when_stopped(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """停止中も開始からの経過時間で打ち切る（正常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.stop(session.id)
    stop_calls_before = h.stop_recording.call_count
    h.clock.current = START + LIMIT

    # 実行
    truncated = h.manager.truncate_if_expired()
    started[0].run_now()

    # 検証
    assert truncated is True
    assert h.stop_recording.call_count == stop_calls_before
    assert h.delivered().result == "truncated"


def test_truncate_if_expired_when_within_limit(audio_path: Path) -> None:
    """上限前は何もしない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)
    h.clock.current = START + LIMIT - timedelta(seconds=1)

    # 実行
    truncated = h.manager.truncate_if_expired()

    # 検証
    assert truncated is False
    assert h.state() == "recording"


def test_truncate_if_expired_when_hotkey_session(audio_path: Path) -> None:
    """ホットキーの録音セッションは対象外（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")
    h.clock.current = START + LIMIT

    # 実行
    truncated = h.manager.truncate_if_expired()

    # 検証
    assert truncated is False


def test_truncate_if_expired_when_save_failed(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打ち切った録音を保存できなければ待機中に戻して failed を届ける（異常系）。"""
    # 準備
    started = defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.save_recording.side_effect = OSError("録音を保存できない")
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.stop(session.id)
    h.clock.current = START + LIMIT

    # 実行
    truncated = h.manager.truncate_if_expired()
    started[0].run_now()

    # 検証
    assert truncated is True
    assert h.state() is None
    assert h.delivered().result == "failed"
    assert h.manager.truncate_if_expired() is False


# === _run_after_confirm ===


def test_run_after_confirm(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """起こした文字を補正して届ける（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.transcribe.return_value = "てすと"
    h.correct.side_effect = None
    h.correct.return_value = "テスト"
    _confirm_hotkey(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    h.append_text.assert_called_once_with(audio_path, "テスト")
    assert h.delivered().text == "テスト"
    h.discard_temporary.assert_called_once_with(audio_path)
    assert h.state() is None


def test_run_after_confirm_when_transcription_failed_from_hotkey(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ホットキーの失敗は知らせて届けない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.transcribe.side_effect = TranscriptionError("文字起こしに失敗した")
    _confirm_hotkey(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    assert "transcription_failed" in h.events()
    h.deliver.assert_not_called()
    assert h.state() is None


def test_run_after_confirm_when_transcription_failed_from_api(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API の失敗は呼び出し元へ届ける（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.transcribe.side_effect = TranscriptionError("文字起こしに失敗した")
    _confirm_api(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    assert h.delivered().result == "failed"
    assert "文字起こしに失敗した" in str(h.delivered().error)


def test_run_after_confirm_when_empty_from_hotkey(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ホットキーの空の結果は届けない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.transcribe.return_value = ""
    _confirm_hotkey(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    h.deliver.assert_not_called()
    assert "transcription_failed" not in h.events()
    assert "delivery_failed" not in h.events()


def test_run_after_confirm_when_empty_from_api(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API の空の結果は届ける（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.transcribe.return_value = ""
    _confirm_api(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    assert h.delivered().result == "transcribed"
    assert h.delivered().text == ""


def test_run_after_confirm_when_deliver_raised_unexpected(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """想定外の例外でも録音セッションは空になる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.deliver.side_effect = RuntimeError("想定外")
    _confirm_hotkey(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    assert "delivery_failed" in h.events()
    assert h.state() is None
    assert str(h.manager.start("hotkey").state) == "recording"


def test_run_after_confirm_when_unknown_output(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """選んだ出力先が無ければ届けられなかったと知らせる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.deliver.side_effect = UnknownOutputError("出力先が無い")
    _confirm_hotkey(h, monkeypatch)

    # 実行
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    assert "delivery_failed" in h.events()
    assert h.state() is None


# === switch_output ===


def test_switch_output_when_transcribing(audio_path: Path) -> None:
    """文字起こし中なら届ける出力先を差し替える（正常系）。"""
    # 準備: 貼り付けて送信で確定し、文字起こしで止まったままにする
    h = make_harness(audio_path)
    transcribe_entered, release_transcribe = _block_until_released(h.transcribe, "てすと")
    h.manager.start("hotkey")
    h.manager.complete(output_id="paste_and_send")
    assert transcribe_entered.wait(timeout=WAIT_SEC)

    # 実行
    h.manager.switch_output("copy_only")
    release_transcribe.set()
    idle = h.wait_until_idle()

    # 検証
    assert idle
    h.notify.assert_any_call("output_changed", "copy_only")
    assert h.deliver.call_args.args[0].output_id == "copy_only"


def test_switch_output_when_delivering(audio_path: Path) -> None:
    """届け始めた後は差し替えない（正常系）。"""
    # 準備: 貼り付けて送信で確定し、届けるところで止まったままにする
    h = make_harness(audio_path)
    deliver_entered, release_deliver = _block_until_released(h.deliver)
    h.manager.start("hotkey")
    h.manager.complete(output_id="paste_and_send")
    assert deliver_entered.wait(timeout=WAIT_SEC)

    # 実行
    h.manager.switch_output("copy_only")
    release_deliver.set()
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert h.deliver.call_args.args[0].output_id == "paste_and_send"
    assert "output_changed" not in h.events()


def test_switch_output_when_preset(audio_path: Path) -> None:
    """カスタムプリセットで確定した録音は差し替えない（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備: プリセットで確定し、文字起こしで止まったままにする
    h = make_harness(audio_path)
    preset = BrowserPreset(title="ChatGPT", url="https://chatgpt.com")
    transcribe_entered, release_transcribe = _block_until_released(h.transcribe, "てすと")
    h.manager.start("hotkey")
    h.manager.complete(preset=preset)
    assert transcribe_entered.wait(timeout=WAIT_SEC)

    # 実行
    h.manager.switch_output("copy_only")
    release_transcribe.set()
    idle = h.wait_until_idle()

    # 検証
    assert idle
    delivered_session = h.deliver.call_args.args[0]
    assert delivered_session.output_id is None
    assert delivered_session.output_preset == preset
    assert "output_changed" not in h.events()


def test_switch_output_when_api_session(audio_path: Path) -> None:
    """API の録音セッションは差し替えない（正常系）。"""
    # 準備: API の録音セッションを確定し、文字起こしで止まったままにする
    h = make_harness(audio_path)
    transcribe_entered, release_transcribe = _block_until_released(h.transcribe, "てすと")
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.complete(session.id)
    assert transcribe_entered.wait(timeout=WAIT_SEC)

    # 実行
    h.manager.switch_output("copy_only")
    output_id = h.current().output_id
    release_transcribe.set()
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert output_id is None
    assert "output_changed" not in h.events()


def test_switch_output_when_same_output(audio_path: Path) -> None:
    """今の出力先と同じなら何もしない（正常系）。"""
    # 準備: 貼り付けて送信で確定し、文字起こしで止まったままにする
    h = make_harness(audio_path)
    transcribe_entered, release_transcribe = _block_until_released(h.transcribe, "てすと")
    h.manager.start("hotkey")
    h.manager.complete(output_id="paste_and_send")
    assert transcribe_entered.wait(timeout=WAIT_SEC)

    # 実行
    h.manager.switch_output("paste_and_send")
    release_transcribe.set()
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert "output_changed" not in h.events()


def test_switch_output_when_idle(audio_path: Path) -> None:
    """待機中・録音中は何もしない（正常系）。"""
    # 準備
    h = make_harness(audio_path)

    # 実行: 録音セッションが無いときと、録音中に呼ぶ
    h.manager.switch_output("copy_only")
    h.manager.start("hotkey")
    h.manager.switch_output("copy_only")

    # 検証
    assert h.current().output_id is None
    assert "output_changed" not in h.events()


# === close ===


def test_close_when_recording(audio_path: Path) -> None:
    """録音中の録音セッションは捨てる（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager.close()

    # 検証
    h.discard_recording.assert_called_once()
    h.save_recording.assert_not_called()
    h.deliver.assert_not_called()
    assert h.state() is None


def test_close_when_idle(audio_path: Path) -> None:
    """待機中は何もしない（正常系）。"""
    # 準備
    h = make_harness(audio_path)

    # 実行
    h.manager.close()

    # 検証
    h.discard_recording.assert_not_called()


# === current ===


def test_current_when_idle(audio_path: Path) -> None:
    """録音セッションが無ければ None を返す（正常系）。"""
    # 準備
    h = make_harness(audio_path)

    # 実行
    session = h.manager.current()

    # 検証
    assert session is None


def test_current_when_recording(audio_path: Path) -> None:
    """ホットキーで始めた後は、入口と状態を持つ録音セッションを返す（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行
    session = h.manager.current()

    # 検証
    assert session is not None
    assert session.entry == "hotkey"
    assert str(session.state) == "recording"


# === complete（文字起こしの進みの知らせ） ===


def test_complete_when_reports_progress(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ホットキーの録音セッションを complete すると、文字起こしへ進みを知らせる関数を渡す。API の録音セッションでは渡さない（正常系）。"""
    # 準備: ホットキーの録音セッションと API の録音セッションを、それぞれ確定して文字起こしの流れを動かす
    report_progress = MagicMock()
    hotkey_harness = make_harness(audio_path, report_progress=report_progress)
    _confirm_hotkey(hotkey_harness, monkeypatch)
    api_harness = make_harness(audio_path, report_progress=report_progress)
    _confirm_api(api_harness, monkeypatch)

    # 実行
    hotkey_harness.manager._run_after_confirm(hotkey_harness.current(), audio_path)
    api_harness.manager._run_after_confirm(api_harness.current(), audio_path)

    # 検証（transcribe の第 2 引数が進みを知らせる関数）
    assert hotkey_harness.transcribe.call_args.args[1] is report_progress
    assert api_harness.transcribe.call_args.args[1] is None


# === start（用語集のプリセット） ===


def _drive_single(
    h: Harness, monkeypatch: pytest.MonkeyPatch, glossary_preset: str | None
) -> Session:
    """1 回の録音を API で始めて確定し、文字起こしから届けるまでを動かして、始めた録音セッションを返す。"""
    defer_workers(monkeypatch)
    session = h.manager.start(
        "api", callback_url=CALLBACK_URL, glossary_preset=glossary_preset
    )
    h.manager.complete(session.id)
    h.manager._run_after_confirm(h.current(), h.audio_path)
    return session


def _drive_continuous(
    h: Harness, monkeypatch: pytest.MonkeyPatch, glossary_preset: str | None
) -> Session:
    """連続録音を API で始めて区間を 1 つ渡し、確定して待機中に戻るまで待って、始めた録音セッションを返す。"""
    session = h.manager.start(
        "api", callback_url=CALLBACK_URL, continuous=True, glossary_preset=glossary_preset
    )
    h.on_segment()(make_segment())
    h.manager.complete(session.id)
    h.wait_until_idle()
    return session


@pytest.mark.parametrize(
    ("drive", "glossary_preset", "expected_preset"),
    [
        pytest.param(_drive_single, "会議", "会議", id="single"),
        pytest.param(_drive_continuous, "会議", "会議", id="continuous"),
        pytest.param(_drive_single, None, None, id="omitted"),
    ],
)
def test_start_when_glossary_preset(
    continuous_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    drive: Callable[[Harness, pytest.MonkeyPatch, str | None], Session],
    glossary_preset: str | None,
    expected_preset: str | None,
) -> None:
    """指定した用語集のプリセットを録音セッションに持たせ、補正へ渡す（正常系）。"""
    # 準備
    h = continuous_harness
    h.transcribe.return_value = "てすと"

    # 実行
    session = drive(h, monkeypatch, glossary_preset)

    # 検証
    assert session.glossary_preset == expected_preset
    h.correct.assert_called_once_with("てすと", expected_preset)


# === start（連続録音） ===


def test_start_when_continuous(continuous_harness: Harness) -> None:
    """連続録音を始める（正常系）。"""
    # 準備
    h = continuous_harness

    # 実行
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)

    # 検証
    assert session.continuous is True
    assert str(session.state) == "recording"
    h.start_continuous_recording.assert_called_once()
    h.start_recording.assert_not_called()


# === stop（連続録音） ===


def test_stop_when_continuous(continuous_harness: Harness) -> None:
    """連続録音は止めずに断る（異常系）。"""
    from voice_paste.shared.errors import SessionConflictError

    # 準備
    h = continuous_harness
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)

    # 実行・検証
    with pytest.raises(SessionConflictError, match="連続録音"):
        h.manager.stop(session.id)
    h.stop_recording.assert_not_called()
    h.stop_continuous_recording.assert_not_called()
    assert h.state() == "recording"


# === complete（連続録音） ===


def test_complete_when_continuous(continuous_harness: Harness) -> None:
    """連続録音を完了すると、最後の区間の後ろに completed を届けて待機中に戻る（正常系）。"""
    # 準備: 区間を 1 つ受けた後、止めるときにもう 1 つ区間を渡す
    h = continuous_harness
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    h.on_segment()(make_segment())
    h.stop_continuous_recording.side_effect = lambda: h.on_segment()(make_segment())

    # 実行
    h.manager.complete(session.id)
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert h.outcome_rows() == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("completed", None, 2),
    ]
    with pytest.raises(SessionNotFoundError):
        h.manager.complete(session.id)


def test_complete_when_continuous_without_segments(continuous_harness: Harness) -> None:
    """区間が無いまま完了すると segment_count=0 の completed だけを届ける（正常系）。"""
    # 準備
    h = continuous_harness
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)

    # 実行
    h.manager.complete(session.id)
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert h.outcome_rows() == [("completed", None, 0)]
    h.save_recording.assert_not_called()
    h.transcribe.assert_not_called()


# === truncate_if_expired（連続録音） ===


def test_truncate_if_expired_when_continuous(continuous_harness: Harness) -> None:
    """連続録音は連続録音の上限時間で打ち切り、残りの区間の後ろに truncated を届ける（正常系）。"""
    # 準備: 1 回の録音の上限は 600 秒、連続録音の上限は 3600 秒。止めるときに区間を 1 つ渡す
    h = continuous_harness
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    h.stop_continuous_recording.side_effect = lambda: h.on_segment()(make_segment())

    # 実行
    h.clock.current = START + EARLY_TRUNCATE
    early = h.manager.truncate_if_expired()
    state_after_early = h.state()
    h.clock.current = START + CONTINUOUS_LIMIT
    late = h.manager.truncate_if_expired()
    idle = h.wait_until_idle()

    # 検証
    assert early is False
    assert state_after_early == "recording"
    assert late is True
    assert idle
    assert h.outcome_rows() == [("transcribed", 1, None), ("truncated", None, 1)]


# === close（連続録音） ===


def test_close_when_continuous(continuous_harness: Harness) -> None:
    """連続録音を捨て、残りの区間と終わりを返さない。区切りのスレッドが区間を渡している最中でも戻る（正常系）。"""
    # 準備: discard_recording は別のスレッドから on_segment を呼び、その終わりを待つ（区切りのスレッドの終わりを待つ Recorder.discard を模す）
    h = continuous_harness
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)

    def _discard() -> None:
        passing = threading.Thread(target=h.on_segment(), args=(make_segment(),), daemon=True)
        passing.start()
        passing.join(timeout=WAIT_SEC * 5)

    h.discard_recording.side_effect = _discard
    closer = threading.Thread(target=h.manager.close, daemon=True)

    # 実行
    closer.start()
    closer.join(timeout=CLOSE_LIMIT_SEC)

    # 検証
    assert not closer.is_alive()
    h.discard_recording.assert_called_once()
    h.save_recording.assert_not_called()
    h.deliver.assert_not_called()
    assert h.state() is None


# === _on_segment ===


def test_on_segment_numbers_in_order(continuous_harness: Harness) -> None:
    """区間に 1 から順に通し番号を付ける（正常系）。"""
    # 準備
    h = continuous_harness
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()

    # 実行
    on_segment(make_segment())
    on_segment(make_segment())
    on_segment(make_segment())
    saved = h.wait_for(lambda: h.save_recording.call_count == 3)

    # 検証
    assert saved
    assert h.saved_segment_numbers() == [1, 2, 3]
    assert h.current().segment_count == 3


def test_on_segment_when_not_continuous(continuous_harness: Harness) -> None:
    """連続録音でなければ区間を捨てる（正常系）。"""
    # 準備: 終了で録音セッションを空にした後にする
    h = continuous_harness
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()
    h.manager.close()

    # 実行
    on_segment(make_segment())

    # 検証
    h.save_recording.assert_not_called()
    h.deliver.assert_not_called()


# === _run_segments ===


def test_run_segments_when_transcription_failed(continuous_harness: Harness) -> None:
    """区間の文字起こしに失敗しても、その区間の failed を返して次の区間へ進む（異常系）。"""
    # 準備: 区間を 3 つ渡し、2 つ目だけ文字起こしに失敗させる
    h = continuous_harness
    h.transcribe.side_effect = ["一つ目", TranscriptionError("二つ目は失敗"), "三つ目"]
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()
    on_segment(make_segment())
    on_segment(make_segment())
    on_segment(make_segment())

    # 実行
    h.manager.complete(session.id)
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert h.outcome_rows() == [
        ("transcribed", 1, None),
        ("failed", 2, None),
        ("transcribed", 3, None),
        ("completed", None, 3),
    ]
    assert "二つ目は失敗" in h.deliver.call_args_list[1].args[1].error


def test_run_segments_when_deliver_blocks(continuous_harness: Harness) -> None:
    """前の区間の返送を待つ間も区間を受け、順を崩さずに返す（正常系）。"""
    # 準備: 1 つ目の区間の返送だけが、テストが許すまで止まる
    h = continuous_harness
    deliver_entered = threading.Event()
    release_deliver = threading.Event()

    def _blocking_deliver(_session: Session, outcome: TranscriptionOutcome) -> None:
        if outcome.segment_number == 1:
            deliver_entered.set()
            release_deliver.wait(timeout=WAIT_SEC * 5)

    h.deliver.side_effect = _blocking_deliver
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()
    on_segment(make_segment())
    assert deliver_entered.wait(timeout=WAIT_SEC)

    def _pass_two_segments() -> None:
        on_segment(make_segment())
        on_segment(make_segment())

    passing = threading.Thread(target=_pass_two_segments, daemon=True)

    # 実行: 返送が止まっている間に区間を 2 つ渡し、その後で返送を許す
    passing.start()
    passing.join(timeout=WAIT_SEC)
    returned = not passing.is_alive()
    release_deliver.set()
    delivered = h.wait_for(lambda: h.deliver.call_count == 3)

    # 検証
    assert returned
    assert delivered
    assert h.outcome_rows() == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("transcribed", 3, None),
    ]


def test_run_segments_when_deliver_raised(
    continuous_harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    """区間を届けるときに例外が出ても、ログに書いて次の区間へ進む（異常系）。"""
    # 準備: 2 つ目の区間の返送だけが RuntimeError を送出する
    h = continuous_harness

    def _raising_deliver(_session: Session, outcome: TranscriptionOutcome) -> None:
        if outcome.segment_number == 2:
            raise RuntimeError("コールバック先に届かない")

    h.deliver.side_effect = _raising_deliver
    caplog.set_level(logging.ERROR)
    h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()

    # 実行: 区間を 3 つ渡す
    on_segment(make_segment())
    on_segment(make_segment())
    on_segment(make_segment())
    delivered = h.wait_for(lambda: h.deliver.call_count == 3)

    # 検証
    assert delivered
    assert h.outcome_rows() == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("transcribed", 3, None),
    ]
    error_messages = [
        record.getMessage() for record in caplog.records if record.levelno == logging.ERROR
    ]
    assert len(error_messages) == 1
    assert "区間を届けられなかった" in error_messages[0]
    assert h.state() == "recording"


# === _on_continuous_failed ===


def test_on_continuous_failed(continuous_harness: Harness) -> None:
    """それまでの区間の後ろに failed の終わりを届けて待機中に戻る（異常系）。"""
    # 準備: 区間を 2 つ受けた後にする
    h = continuous_harness
    session = h.manager.start("api", callback_url=CALLBACK_URL, continuous=True)
    on_segment = h.on_segment()
    on_segment(make_segment())
    on_segment(make_segment())

    # 実行
    h.on_failed()("VAD の失敗")
    idle = h.wait_until_idle()

    # 検証
    assert idle
    assert h.outcome_rows() == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("failed", None, 2),
    ]
    assert h.delivered().error == "VAD の失敗"
    with pytest.raises(SessionNotFoundError):
        h.manager.complete(session.id)
    restarted = h.manager.start("hotkey")
    assert str(restarted.state) == "recording"
