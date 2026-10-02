"""features/session/service.py（SessionManager の start・pause・stop・complete・cancel・truncate_if_expired・_run_after_confirm・close）の単体テスト。

SessionDeps の関数は全て Mock に差し替える。
ワーカースレッドは、起動を覚えるだけの偽物（defer_workers）に差し替えて、テストが動かすタイミングを決める。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.voice_paste.features.session.helpers import (
    CALLBACK_URL,
    LIMIT,
    START,
    Harness,
    defer_workers,
    make_harness,
)
from voice_paste.shared.errors import (
    MicrophoneUnavailableError,
    SessionBusyError,
    SessionNotFoundError,
    TranscriptionError,
    UnknownOutputError,
)

WAIT_SEC = 2.0


@pytest.fixture
def audio_path(tmp_path: Path) -> Path:
    """save_recording が返す録音のパスを返す。"""
    return tmp_path / "20261001120000_s1.wav"


def _confirm_hotkey(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """ホットキーのセッションを始めて確定し、文字起こしから届けるまでは動かさずに止めておく。"""
    defer_workers(monkeypatch)
    h.manager.start("hotkey")
    h.manager.complete()


def _confirm_api(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """API のセッションを始めて確定し、文字起こしから届けるまでは動かさずに止めておく。"""
    defer_workers(monkeypatch)
    session = h.manager.start("api", callback_url=CALLBACK_URL)
    h.manager.complete(session.id)


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
    """API のセッションに一時停止のホットキーが来ても変えない（正常系）。"""
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
    """止めたセッションは何も変えない（正常系）。"""
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


def test_complete_when_output_target(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """確定の操作で選んだ出力先の ID と宛先を、届けるときの Session に持たせる（正常系）。"""
    # 準備
    defer_workers(monkeypatch)
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行
    h.manager.complete(output_id="ai_chat", output_target="https://chatgpt.com")
    h.manager._run_after_confirm(h.current(), audio_path)

    # 検証
    delivered_session = h.deliver.call_args.args[0]
    assert delivered_session.output_id == "ai_chat"
    assert delivered_session.output_target == "https://chatgpt.com"


def test_complete_when_hotkey_on_api_session(audio_path: Path) -> None:
    """API のセッションにホットキーの確定が来ても変えない（正常系）。"""
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
    """完了済みのセッションは断る（異常系）。"""
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


# === cancel ===


def test_cancel_when_recording(audio_path: Path) -> None:
    """録音を捨てて待機中に戻す（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("hotkey")

    # 実行
    h.manager.cancel()

    # 検証
    h.discard_recording.assert_called_once()
    h.save_recording.assert_not_called()
    assert h.state() is None


def test_cancel_when_api_session(audio_path: Path) -> None:
    """API のセッションに取り消しのホットキーが来ても変えない（正常系）。"""
    # 準備
    h = make_harness(audio_path)
    h.manager.start("api", callback_url=CALLBACK_URL)

    # 実行
    h.manager.cancel()

    # 検証
    h.discard_recording.assert_not_called()
    assert h.state() == "recording"


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
    """ホットキーのセッションは対象外（正常系）。"""
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
    """想定外の例外でもセッションは空になる（正常系）。"""
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


# === close ===


def test_close_when_recording(audio_path: Path) -> None:
    """録音中のセッションは捨てる（正常系）。"""
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
