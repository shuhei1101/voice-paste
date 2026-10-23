"""複合ユースケース「外の端末のブラウザから音声を送って文字で受け取る」の E2E テスト。

常駐アプリは pytest のプロセスの中で `build_handlers` で配線し、API は 127.0.0.1 の空きポートで待ち受ける（起動・トレイ・ホットキーの受付は通さない）。
画面は Windows の Edge を headless で起動し、DevTools Protocol で `http://localhost:{ポート}/web/` を操作する（localhost の Origin は許す Origin に入れる）。
Edge のマイクは偽物で、Windows の音声合成（SAPI）で書き出した WAV を流す。
文字起こしはローカルの Whisper（GPU）で、用語集は設定のフォルダの CSV。クリップボードは、画面が書いた文字を呼び出しで見張って確かめる。
ホットキーの録音を重ねるケースは、録音の入力を WAV を流すものに、貼り付けのキーを送らずに控えるものに差し替える。
文字起こしの失敗と読めない形式のケースは、エンジンを失敗を返す関数に差し替える（読めない形式は差し替えず、形式の確認で断られる）。
許されていない Origin のシナリオは画面を通さず、テストから HTTP で送る。
実機の Windows・Edge・GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.browser import wait_for
from tests.support.inprocess import (
    encode_audio,
    make_settings,
    silence_input,
    speech_input,
)
from tests.support.web_scene import (
    STUB_TEXT,
    OpenEdge,
    StartInProcess,
    build_scene,
    record_for,
)
from voice_paste.shared.errors import TranscriptionError

pytestmark = pytest.mark.real_machine

RECORD_SEC = 4
"""画面で録る長さ（秒。書き出した文を 1 回以上含む）。"""

RESULT_TIMEOUT_SEC = 90.0
"""送ってから、画面に起こした文字が出るまで待つ上限。"""

GLOSSARY_FILE_NAME = "yogo.csv"
"""設定のフォルダに置く、今までの用語集の CSV の名前。"""

GLOSSARY_ROWS = "誤変換,正しい表記,使う\nテスト,試験,1\n"
"""用語集の行（書き出した文の言葉を置き換えるオンの行）。"""

CORRECTED_WORD = "試験"
"""用語集で置き換わった、正しい表記。"""

PASTE_AND_SEND = "paste_and_send"
"""確定に選ぶ出力先の ID（貼り付けて送信）。"""

BROKEN_AUDIO = b"this is not audio at all" * 100
"""音声として読めない中身。"""

TRANSCRIPTION_ERROR_TEXT = "文字起こしに失敗させた"
"""差し替えた文字起こしが送出する例外のメッセージ。"""

FAILED_STATUS = "文字起こし失敗"
"""文字起こしが失敗した件の状態の文言。"""


def _put_glossary(tmp_path: Path) -> None:
    """設定のフォルダに、用語集の CSV を置く。"""
    (tmp_path / GLOSSARY_FILE_NAME).write_text(GLOSSARY_ROWS, encoding="utf-8")


def test_normal_when_record_in_page(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画面で録って止めると、用語集で補正した文字が結果の先頭に出て、コピーでクリップボードに入り、端末に 1 件残る。PC の履歴に音声と .txt が残る（正常シナリオ（画面で録る））。"""
    # 準備
    _put_glossary(tmp_path)
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch)
    scene.page.watch_clipboard()

    # 実行
    record_for(scene.page, RECORD_SEC)
    done = wait_for(
        lambda: bool(scene.page.results()) and CORRECTED_WORD in scene.page.results()[0]["text"],
        RESULT_TIMEOUT_SEC,
    )
    text = scene.page.results()[0]["text"]
    scene.page.click("copy_button")

    # 検証
    assert done
    assert wait_for(lambda: scene.page.copied_text() == text)
    stored = scene.page.stored_results()
    assert len(stored) == 1
    assert stored[0]["text"] == text
    [recording] = scene.app.history_files(".webm")
    [text_file] = scene.app.history_files(".txt")
    assert recording.stem == text_file.stem


def test_normal_when_select_file(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き出した文を MP3 にしたファイルを選ぶと、用語集で補正した文字が結果の先頭に出て、端末に 1 件残る（正常シナリオ（ファイルを選んで送る））。"""
    # 準備
    _put_glossary(tmp_path)
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch)

    # 実行
    scene.page.choose_file(encode_audio(scene.speech_wav, "mp3"), "speech.mp3", "audio/mpeg")
    done = wait_for(
        lambda: bool(scene.page.results()) and CORRECTED_WORD in scene.page.results()[0]["text"],
        RESULT_TIMEOUT_SEC,
    )

    # 検証
    assert done
    stored = scene.page.stored_results()
    assert len(stored) == 1
    assert CORRECTED_WORD in stored[0]["text"]


def test_normal_when_hotkey_recording(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """ホットキーの録音中に音声ファイルを送っても、画面に起こした文字が出て、ホットキーの録音は録音中のまま続き、確定するといつもどおり貼り付けまで進む（正常シナリオ（ホットキーの録音中に送る））。"""
    # 準備
    _put_glossary(tmp_path)
    scene = build_scene(
        start_inprocess,
        open_edge,
        tmp_path,
        monkeypatch,
        wav_input=speech_input(tmp_path),
    )
    scene.app.start_hotkey()
    assert scene.app.manager.current() is not None

    # 実行
    scene.page.record_requests()
    scene.page.choose_file(scene.speech_wav.read_bytes(), "speech.wav", "audio/wav")
    done = wait_for(
        lambda: bool(scene.page.results()) and CORRECTED_WORD in scene.page.results()[0]["text"],
        RESULT_TIMEOUT_SEC,
    )
    still_recording = scene.app.manager.current() is not None
    scene.app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert scene.page.responses()[0]["status"] == 202
    assert done
    assert still_recording
    assert scene.app.wait_idle()
    assert len(scene.app.keys.pasted) == 1


def test_error_when_unreadable_format(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """音声でない中身の MP3 を送ると 415 で返り、画面に読めない形式であることが出て件は増えない。続けて正しい MP3 を送ると受け付けられる（異常シナリオ（読めない形式を送る））。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    scene.page.record_requests()

    # 実行
    scene.page.choose_file(BROKEN_AUDIO, "broken.mp3", "audio/mpeg")
    refused = wait_for(lambda: len(scene.page.responses()) == 1)
    error = wait_for(lambda: scene.page.error() is not None)
    after_refused = scene.page.results()
    scene.page.choose_file(encode_audio(scene.speech_wav, "mp3"), "speech.mp3", "audio/mpeg")
    accepted = wait_for(lambda: len(scene.page.responses()) == 2)

    # 検証
    assert refused
    assert scene.page.responses()[0]["status"] == 415
    assert "problem+json" in scene.page.responses()[0]["content_type"]
    assert error
    assert after_refused == []
    assert accepted
    assert scene.page.responses()[1]["status"] == 202
    assert wait_for(lambda: len(scene.page.results()) == 1)


def test_error_when_transcription_failed(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文字起こしが失敗すると画面に失敗が出る。端末の音声は残り送り直せて、エンジンを戻して送り直すと文字が出る（異常シナリオ（文字起こしに失敗））。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    assert scene.stub is not None
    scene.stub.error = TranscriptionError(TRANSCRIPTION_ERROR_TEXT)

    # 実行
    record_for(scene.page, RECORD_SEC)
    failed = wait_for(
        lambda: bool(scene.page.results()) and scene.page.results()[0]["status"] == FAILED_STATUS
    )
    kept = scene.page.kept_audio()
    resend_enabled = not scene.page.is_disabled("resend_button")
    download_enabled = not scene.page.is_disabled("download_button")
    scene.stub.error = None
    scene.page.click("resend_button")
    resent = wait_for(
        lambda: bool(scene.page.results()) and scene.page.results()[0]["text"] == STUB_TEXT
    )

    # 検証
    assert failed
    assert kept is not None
    assert resend_enabled
    assert download_enabled
    assert resent
    assert len(scene.page.results()) == 1


def test_error_when_origin_not_allowed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
) -> None:
    """許す Origin の一覧に無い Origin から送ると 403 で返り、キューにジョブが積まれず、PC の履歴にも残らない（異常シナリオ（許可されていない Origin から送る））。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    api = app.start_web_api(allowed=False)

    # 実行
    response = api.post_web_audio(b"RIFF" + bytes(100), origin="https://not-allowed.example.com")

    # 検証
    assert response.status_code == 403
    assert "problem+json" in response.headers["content-type"]
    assert "job_id" not in response.json()
    assert app.web_temp_files() == []
    assert [path for path in app.paths.history_dir.rglob("*") if path.is_file()] == []
