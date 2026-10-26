"""複合ユースケース「ほかのシステムから連続して録音し、区切りごとに文字で受け取る」の E2E テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、API は `build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて叩く。
返送先は 127.0.0.1 でテストが立てる受け口。録音の入力は、Windows の音声合成（SAPI）で決めた文を読み上げた WAV を実時間で流すものに
差し替え、マイクもスピーカーも通さない。貼り付けのキーは差し替えて、送られないことを確かめる。
話し声の判定（Silero VAD）・文字起こし（ローカルの Whisper・GPU）・クリップボードは実物を使う（クリップボードはテストの後に元の文字へ戻す）。
実機の Windows と GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.inprocess import (
    LONG_READING,
    VOLUME_BEFORE,
    InProcessApi,
    InProcessApp,
    complete_session,
    fail_transcription_of_segment,
    make_settings,
    read_wav,
    silence_input,
    speech_sequence_input,
    start_continuous,
    wait_for_continuous_end,
)
from voice_paste.features.outputs.callback import service as callback_service
from voice_paste.features.outputs.callback.service import CALLBACK_RETRY_COUNT
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.recording.segmenter import MAX_SEGMENT_SEC, SEGMENT_PAD_SEC
from voice_paste.features.session.types import SessionState
from voice_paste.shared.types import Entry

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]
Payload = dict[str, Any]

SEGMENT_GAP_SEC = 3.0
"""文と文の間に挟む無音の長さ。区切る無音の長さの既定（2 秒）より長くして、文ごとに区切らせる。"""

SHORT_GAP_SEC = 0.4
"""話し続ける読み上げで、文と文の間に挟む無音の長さ。区切る無音の長さの既定（2 秒）より短くして、無音では区切らせない。"""

NO_SPEECH_SEC = 4.0
"""話さないまま完了するときに流す無音の長さ。"""

SHORT_SESSION_LIMIT_SEC = 25
"""テストで待てる連続録音のセッションの上限時間。3 文の読み上げを流し終えるより後にする。"""

LIMIT_TAIL_SEC = 40.0
"""上限での打ち切りのとき、読み上げを流し終えた後に流し続ける無音の長さ（上限時間より長くする）。"""

STOPPED_TIMEOUT_SEC = 5.0
"""打ち切りの後、録音の入力が止まるのを待つ上限。"""

SHORT_RETRY_BASE_SEC = 0.05
"""テストで待てる返送の再送の間隔の基数。"""

TROUBLED_SEGMENT = 2
"""文字起こしの失敗・返送の失敗を起こさせる区間の通し番号。"""

THREE_SENTENCES: tuple[tuple[str, str], ...] = (
    ("これはテストです", "テスト"),
    ("今日はいい天気です", "天気"),
    ("明日は晴れるでしょう", "晴れ"),
)
"""読み上げる 3 文と、それぞれを起こした文字に含まれるはずの言葉。"""

def _sentences(pairs: Sequence[tuple[str, str]]) -> list[str]:
    """文と言葉の組から、読み上げる文だけを順に返す。"""
    return [sentence for sentence, _word in pairs]


def _words(pairs: Sequence[tuple[str, str]]) -> list[str]:
    """文と言葉の組から、起こした文字に含まれるはずの言葉だけを順に返す。"""
    return [word for _sentence, word in pairs]


def _segments(payloads: Sequence[Payload]) -> list[Payload]:
    """届いた返送のうち、区間の返送（通し番号がある）だけを届いた順に返す。"""
    return [payload for payload in payloads if payload["segment_number"] is not None]


def _end(payloads: Sequence[Payload]) -> Payload:
    """届いた返送のうち、連続録音の終わりが 1 回だけ届いていることを確かめて、その返送を返す。"""
    ends = [payload for payload in payloads if payload["segment_number"] is None]
    assert len(ends) == 1
    return ends[0]


def _segment_recordings(app: InProcessApp) -> list[Path]:
    """履歴に残った区間の録音の WAV を、通し番号の順に返す。"""
    return sorted(app.history_files(".wav"), key=lambda path: int(path.stem.rsplit("_", 1)[1]))


def _duration_sec(wav_path: Path) -> float:
    """WAV の録音の長さ（秒）を返す。"""
    return len(read_wav(wav_path)) / SAMPLE_RATE


def _assert_numbered_in_order(segments: Sequence[Payload], session_id: str) -> None:
    """区間の返送が、同じセッションの 1 から始まる通し番号の順に、起こせた文字として届いていることを確かめる。"""
    assert [segment["segment_number"] for segment in segments] == list(range(1, len(segments) + 1))
    for segment in segments:
        assert segment["session_id"] == session_id
        assert segment["result"] == "transcribed"
        assert segment["error"] is None
        assert segment["segment_count"] is None


def _assert_each_word(segments: Sequence[Payload], words: Sequence[str]) -> None:
    """区間ごとに、起こした文字がその区間で読み上げた文の言葉を含むことを確かめる。"""
    assert len(segments) == len(words)
    for segment, word in zip(segments, words, strict=True):
        assert word in segment["text"]


def _assert_all_words(segments: Sequence[Payload], words: Sequence[str]) -> None:
    """区間の文字を通し番号の順につないだものが、読み上げた文の言葉を全て含むことを確かめる。"""
    joined = "".join(segment["text"] for segment in segments)
    for word in words:
        assert word in joined


def _assert_completed(payloads: Sequence[Payload], session_id: str, segment_count: int) -> None:
    """連続録音の終わり（completed と区間の数）が、最後に 1 回だけ届いていることを確かめる。"""
    end = _end(payloads)
    assert end == {
        "session_id": session_id,
        "result": "completed",
        "text": "",
        "error": None,
        "segment_number": None,
        "segment_count": segment_count,
    }
    assert payloads[-1] == end


def _assert_history_matches(app: InProcessApp, session_id: str, segments: Sequence[Payload]) -> None:
    """履歴に区間ごとの録音と起こした文字が残り、文字は返送した中身と一致することを確かめる。"""
    recordings = _segment_recordings(app)
    assert len(recordings) == len(segments)
    for recording, segment in zip(recordings, segments, strict=True):
        assert session_id in recording.name
        assert recording.with_suffix(".txt").read_text(encoding="utf-8") == segment["text"]


def _assert_can_start_again(api: InProcessApi, app: InProcessApp, receiver: CallbackReceiver) -> None:
    """続けて API の開始を呼ぶと次の録音を始められることを確かめる。"""
    assert app.wait_idle()
    assert api.start_session(receiver.url)[0].status_code == 202


def test_normal(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    receiver: CallbackReceiver,
    clipboard_sentinel: str,
) -> None:
    """連続録音で話すと、区切りごとの文字が通し番号の順に届き、完了で終わりが届く（正常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True),
        wav_input=speech_sequence_input(
            tmp_path, _sentences(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
        ),
    )
    api = app.start_api()

    # 実行: 連続録音を始め、読み上げを流し終えたら完了を呼ぶ
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)

    # 検証
    segments = _segments(payloads)
    _assert_numbered_in_order(segments, session_id)
    _assert_each_word(segments, _words(THREE_SENTENCES))
    _assert_completed(payloads, session_id, segment_count=3)
    assert len(payloads) == 4
    # API からの連続録音で貼り付けが起きない（クリップボードが録音前のまま）
    assert pyperclip.paste() == clipboard_sentinel
    assert app.keys.pasted == []
    assert app.keys.enters == 0
    _assert_history_matches(app, session_id, segments)
    _assert_can_start_again(api, app, receiver)


def test_normal_when_speaking_without_pause(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """話し続けて無音が来なくても、区間の最大の長さで区切って届け、完了で終わりが届く（正常シナリオ）。"""
    # 準備: 無音で区切らせず、区間の最大の長さを超えて読み上げ続ける
    wav_input = speech_sequence_input(
        tmp_path, _sentences(LONG_READING), gap_sec=SHORT_GAP_SEC
    )
    assert wav_input.duration_sec > MAX_SEGMENT_SEC
    app = start_inprocess(settings=make_settings(), wav_input=wav_input)
    api = app.start_api()

    # 実行
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)

    # 検証
    segments = _segments(payloads)
    assert len(segments) >= 2
    _assert_numbered_in_order(segments, session_id)
    assert _duration_sec(_segment_recordings(app)[0]) <= MAX_SEGMENT_SEC + SEGMENT_PAD_SEC
    _assert_all_words(segments, _words(LONG_READING))
    _assert_completed(payloads, session_id, segment_count=len(segments))


def test_normal_when_no_speech(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """話さないまま完了すると、区間は届かず、区間の数 0 の終わりだけが届く（正常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(),
        wav_input=silence_input(tmp_path, seconds=NO_SPEECH_SEC, realtime=True),
    )
    api = app.start_api()

    # 実行: 連続録音を始め、無音を流し終えたら完了を呼ぶ
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)

    # 検証
    assert _segments(payloads) == []
    _assert_completed(payloads, session_id, segment_count=0)
    assert len(payloads) == 1
    assert app.history_files(".wav") == []
    _assert_can_start_again(api, app, receiver)


def test_error_when_session_limit_reached(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """完了が来ないまま上限時間に達すると、録音を止めてそこまでの区間と打ち切りが届く（異常シナリオ）。"""
    # 準備: 連続録音のセッションの上限時間を短くし、読み上げを流し終えた後は無音を流し続ける
    app = start_inprocess(
        settings=make_settings(continuous_session_limit_sec=SHORT_SESSION_LIMIT_SEC),
        wav_input=speech_sequence_input(
            tmp_path,
            _sentences(THREE_SENTENCES),
            gap_sec=SEGMENT_GAP_SEC,
            tail_silence_sec=LIMIT_TAIL_SEC,
        ),
    )
    api = app.start_api()
    app.start_limit_timer()

    # 実行: 連続録音を始め、完了を呼ばずに上限を待つ
    session_id = start_continuous(api, receiver)
    payloads = wait_for_continuous_end(receiver)

    # 検証
    segments = _segments(payloads)
    _assert_numbered_in_order(segments, session_id)
    _assert_each_word(segments, _words(THREE_SENTENCES))
    end = _end(payloads)
    assert end["session_id"] == session_id
    assert end["result"] == "truncated"
    assert end["text"] == ""
    assert end["segment_count"] == len(segments)
    assert payloads[-1] == end
    # マイクの録音が止まり、システム音量が録音前の値に戻っている
    assert app.wav_input.wait_played_out(STOPPED_TIMEOUT_SEC)
    assert app.volume.restored == [VOLUME_BEFORE]
    _assert_can_start_again(api, app, receiver)


def test_error_when_hotkey_during_continuous_recording(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """連続録音の間にホットキーで録音を始めると、処理中と知らされ、連続録音は続く（異常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(),
        wav_input=speech_sequence_input(
            tmp_path, _sentences(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
        ),
    )
    api = app.start_api()
    session_id = start_continuous(api, receiver)

    # 実行: 完了を呼ぶ前にホットキーの入口から録音を始める
    app.start_hotkey()

    # 検証: 処理中のダイアログを出す呼び出しが 1 回あり、2 つ目の録音が始まらず、連続録音が録音中のまま続く
    assert app.notifications.count("busy") == 1
    assert app.wav_input.open_count == 1
    session = app.manager.current()
    assert session is not None
    assert session.id == session_id
    assert session.entry == Entry.API
    assert session.continuous
    assert session.state == SessionState.RECORDING
    # 完了を呼ぶと、区間の文字と終わりが返送先へ届く
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)
    segments = _segments(payloads)
    _assert_numbered_in_order(segments, session_id)
    _assert_each_word(segments, _words(THREE_SENTENCES))
    _assert_completed(payloads, session_id, segment_count=3)


def test_error_when_segment_transcription_failed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """区間の文字起こしに失敗しても連続録音は止まらず、その区間の失敗が通し番号つきで届く（異常シナリオ）。"""
    # 準備: 通し番号 2 の区間だけ文字起こしに失敗させる
    fail_transcription_of_segment(monkeypatch, TROUBLED_SEGMENT)
    app = start_inprocess(
        settings=make_settings(),
        wav_input=speech_sequence_input(
            tmp_path, _sentences(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
        ),
    )
    api = app.start_api()

    # 実行
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)

    # 検証
    segments = _segments(payloads)
    assert [segment["segment_number"] for segment in segments] == [1, 2, 3]
    assert [segment["result"] for segment in segments] == ["transcribed", "failed", "transcribed"]
    assert segments[1]["text"] == ""
    assert segments[1]["error"]
    assert THREE_SENTENCES[0][1] in segments[0]["text"]
    assert THREE_SENTENCES[2][1] in segments[2]["text"]
    _assert_completed(payloads, session_id, segment_count=3)
    assert len(_segment_recordings(app)) == 3
    _assert_can_start_again(api, app, receiver)


def test_error_when_segment_callback_unreachable(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    receiver: CallbackReceiver,
) -> None:
    """区間の返送が届かなくても、ログに書いて次の区間へ進み、ほかの区間と終わりが届く（異常シナリオ）。"""
    # 準備: 通し番号 2 の区間の返送にだけ 500 を返し続け（1 回目と再送の全て）、再送の間隔を短くする
    monkeypatch.setattr(callback_service, "CALLBACK_RETRY_BASE_SEC", SHORT_RETRY_BASE_SEC)
    receiver.statuses = [200] + [500] * (1 + CALLBACK_RETRY_COUNT)
    caplog.set_level(logging.WARNING)
    app = start_inprocess(
        settings=make_settings(),
        wav_input=speech_sequence_input(
            tmp_path, _sentences(THREE_SENTENCES), gap_sec=SEGMENT_GAP_SEC
        ),
    )
    api = app.start_api()

    # 実行
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, session_id)
    payloads = wait_for_continuous_end(receiver)

    # 検証: 通し番号 2 の区間の返送が、1 回目と再送の回数だけ送られている
    sent_for_unreachable = [
        payload for payload in payloads if payload["segment_number"] == TROUBLED_SEGMENT
    ]
    assert len(sent_for_unreachable) == 1 + CALLBACK_RETRY_COUNT
    # ログに、届かなかったことと session_id・通し番号 2 が書かれている
    error_messages = [
        record.getMessage() for record in caplog.records if record.levelno == logging.ERROR
    ]
    assert any(
        "返送先に届かなかった" in message
        and session_id in message
        and f"区間: {TROUBLED_SEGMENT}" in message
        for message in error_messages
    )
    # 通し番号 1 と 3 の区間の文字と、連続録音が終わったことが、この順に届いている
    delivered = [
        payload for payload in payloads if payload["segment_number"] != TROUBLED_SEGMENT
    ]
    segments = _segments(delivered)
    assert [segment["segment_number"] for segment in segments] == [1, 3]
    assert THREE_SENTENCES[0][1] in segments[0]["text"]
    assert THREE_SENTENCES[2][1] in segments[1]["text"]
    _assert_completed(delivered, session_id, segment_count=3)
    assert len(delivered) == 3
    _assert_can_start_again(api, app, receiver)
