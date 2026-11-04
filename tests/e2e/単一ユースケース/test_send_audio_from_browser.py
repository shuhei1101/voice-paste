"""単一ユースケース「ブラウザから音声を送信する」の E2E テスト。

常駐アプリは pytest のプロセスの中で `build_handlers` で配線し、API は 127.0.0.1 の空きポートで待ち受ける（起動・トレイ・ホットキーの受付は通さない）。
画面は Windows の Edge を headless で起動し、DevTools Protocol で `http://localhost:{ポート}/web/` を操作する（localhost の Origin は許す Origin に入れる）。
Edge のマイクは偽物で、Windows の音声合成（SAPI）で書き出した WAV を流す。
文字起こしのエンジンは、受けた音声のパスを控えて決めた文を返す関数に差し替える（文字起こしそのものは確かめない）。
許されていない Origin のシナリオは画面を通さず、テストから HTTP で送信する。
実機の Windows と Edge が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.browser import wait_for
from tests.support.inprocess import (
    FIRST_PRESET_NAME,
    SECOND_PRESET_NAME,
    encode_audio,
    make_glossary_preset_settings,
    make_settings,
    requires_web_transcription,
    silence_input,
    spy_on_correct_presets,
)
from tests.support.web_scene import STUB_TEXT, OpenEdge, StartInProcess, build_scene, record_for

pytestmark = [pytest.mark.real_machine, requires_web_transcription]

RECORD_SEC = 2
"""画面で録る長さ（秒）。"""

OVER_LIMIT_FILE_BYTES = 99_999_900
"""ファイルは本文の上限（100,000,000 バイト）未満でも、multipart の枠を加えると上限を超える大きさ。"""

BROKEN_AUDIO = b"this is not audio at all" * 100
"""音声として読めない中身。"""

RECORDING_LIMIT_MS = 1_800_000
"""画面の録音の上限時間（ミリ秒。30 分）。"""

FAILED_TITLE = "送信失敗"
"""送信が届かなかったときに画面へ出す見出し。"""

PRESET_OPTION_COUNT = 3
"""用語集のプリセットの選択欄の選択肢の数（既定の項目と、設定の用語集のプリセット 2 つ）。"""

PRESET_NOT_FOUND_TITLE = "選択したプリセットが見つかりません"
"""選んだ用語集のプリセットが一覧に無いときに画面へ出す見出し。"""


def test_normal_when_record_in_page(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画面で録って止めると、端末に 1 件残し、202 で受け付けられて結果の一覧に待ちの件が出る（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    assert scene.stub is not None
    scene.stub.hold()
    scene.page.record_requests()
    # 実行
    record_for(scene.page, RECORD_SEC)
    arrived = wait_for(lambda: len(scene.page.responses()) == 1 and len(scene.page.results()) == 1)
    # 検証
    assert arrived
    response = scene.page.responses()[0]
    assert response["status"] == 202
    job_id = scene.page.stored_results()[0]["job_id"]
    kept = scene.page.kept_audio()
    assert kept is not None
    assert kept["recorded_at"]
    assert kept["job_id"] == job_id
    assert scene.api.get_job(job_id).json()["state"] in ("queued", "running")
    assert scene.page.results()[0]["status"] in ("文字起こし待ち", "文字起こし中")
    assert wait_for(lambda: len(scene.stub.paths) == 1)
    scene.stub.release.set()


def test_normal_when_select_file(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MP3 のファイルを選ぶとすぐ送信し、202 で受け付けられる。端末に残した音声は置き換わらない（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    assert scene.stub is not None
    scene.stub.hold()
    mp3 = encode_audio(scene.speech_wav, "mp3")
    scene.page.record_requests()
    # 実行
    scene.page.choose_file(mp3, "speech.mp3", "audio/mpeg")
    arrived = wait_for(lambda: len(scene.page.responses()) == 1 and len(scene.page.results()) == 1)
    # 検証
    assert arrived
    assert scene.page.responses()[0]["status"] == 202
    job_id = scene.page.stored_results()[0]["job_id"]
    assert scene.api.get_job(job_id).json()["state"] in ("queued", "running")
    assert scene.page.kept_audio() is None
    assert scene.page.results()[0]["source"].startswith("speech.mp3")
    assert wait_for(lambda: len(scene.stub.paths) == 1)
    scene.stub.release.set()


def test_normal_when_recording_limit_reached(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画面の時計を録音の上限（30 分）まで進めると録音が止まり、そこまでの音声が端末に残って送信される（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    scene.page.record_requests()
    scene.page.watch_visible("limit-notice")
    scene.page.click("record_button")
    assert scene.page.wait_until("!document.getElementById('recorder').hidden")
    # 実行
    scene.page.advance_clock(RECORDING_LIMIT_MS)
    arrived = wait_for(lambda: len(scene.page.responses()) == 1)
    # 検証
    assert arrived
    assert scene.page.responses()[0]["status"] == 202
    kept = scene.page.kept_audio()
    assert kept is not None
    assert kept["duration_sec"] == 1800
    # 上限の知らせは、止まってから送信が終わるまでの間だけ出る
    assert scene.page.was_seen()


def test_error_when_send_failed(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API の待ち受けを止めて録音を止めると送信失敗になる。端末の音声は残り、待ち受けを戻して再送すると 202 で受け付けられる（異常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    scene.page.click("record_button")
    assert scene.page.wait_until("!document.getElementById('recorder').hidden")
    port = scene.api.port
    scene.api.close()
    scene.page.record_requests()
    # 実行
    scene.page.click("stop_button")
    failed = wait_for(lambda: scene.page.kept_state() == FAILED_TITLE)
    # 検証
    assert failed
    error = scene.page.error()
    assert error is not None
    assert error[0] == FAILED_TITLE
    assert not scene.page.is_disabled("resend_button")
    assert not scene.page.is_disabled("download_button")
    kept = scene.page.kept_audio()
    assert kept is not None
    assert kept["state"] == "send_failed"
    # 待ち受けを戻して再送する
    scene.app.start_web_api(port=port, start_queue=False)
    scene.page.click("resend_button")
    assert wait_for(lambda: len(scene.page.results()) == 1)
    assert scene.page.responses()[-1]["status"] == 202
    assert scene.page.kept_audio()["state"] == "sent"


def test_error_when_unreadable_format(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """音声でない中身の MP3 を選ぶと 415 で返り、読めない形式であることが画面に出る。件は増えず一時のファイルも書かれない（異常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    scene.page.record_requests()
    # 実行
    scene.page.choose_file(BROKEN_AUDIO, "broken.mp3", "audio/mpeg")
    arrived = wait_for(lambda: len(scene.page.responses()) == 1)
    # 検証
    assert arrived
    response = scene.page.responses()[0]
    assert response["status"] == 415
    assert "problem+json" in response["content_type"]
    assert "job_id" not in response["body"]
    assert wait_for(lambda: scene.page.error() is not None)
    assert scene.page.error()[0] == "非対応形式"
    assert scene.page.results() == []
    assert scene.app.web_temp_files() == []


def test_error_when_too_large(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本文の上限（100,000,000 バイト）を超える大きさのファイルを選ぶと 413 で返り、大きすぎることが画面に出る。件は増えず一時のファイルも書かれない（異常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    scene.page.record_requests()
    # 実行
    scene.page.choose_empty_file(OVER_LIMIT_FILE_BYTES, "huge.mp3", "audio/mpeg")
    arrived = wait_for(lambda: len(scene.page.responses()) == 1)
    # 検証
    assert arrived
    response = scene.page.responses()[0]
    assert response["status"] == 413
    assert "problem+json" in response["content_type"]
    assert "job_id" not in response["body"]
    assert wait_for(lambda: scene.page.error() is not None)
    assert scene.page.error()[0] == "ファイルサイズ超過"
    assert scene.page.results() == []
    assert scene.app.web_temp_files() == []


def test_error_when_origin_not_allowed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """許す Origin の一覧に無い Origin から送信すると 403 で返り、一時のファイルも履歴も書かれない（異常系）。"""
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


def test_normal_when_select_glossary_preset(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """選択欄に既定と設定のプリセットが並び、2 つ目のプリセットを選んで MP3 のファイルを送信すると 202 で受け付けられ、補正が選んだプリセットの名前で呼ばれる（正常シナリオ（用語集のプリセットを選ぶ））。"""
    # 準備: 用語集のプリセットが 2 つあり、補正は受けたプリセットの名前を控える関数に差し替える
    corrected = spy_on_correct_presets(monkeypatch)
    scene = build_scene(
        start_inprocess,
        open_edge,
        tmp_path,
        monkeypatch,
        stub_text=STUB_TEXT,
        settings=make_glossary_preset_settings(tmp_path),
    )
    assert scene.stub is not None
    scene.stub.hold()
    assert wait_for(lambda: len(scene.page.preset_options()) == PRESET_OPTION_COUNT)
    mp3 = encode_audio(scene.speech_wav, "mp3")
    scene.page.record_requests()
    # 実行
    scene.page.select_preset(SECOND_PRESET_NAME)
    scene.page.choose_file(mp3, "speech.mp3", "audio/mpeg")
    arrived = wait_for(lambda: len(scene.page.responses()) == 1 and len(scene.page.results()) == 1)
    # 検証
    assert scene.page.preset_options() == [
        ("", f"設定に従う（{FIRST_PRESET_NAME}）"),
        (FIRST_PRESET_NAME, FIRST_PRESET_NAME),
        (SECOND_PRESET_NAME, SECOND_PRESET_NAME),
    ]
    assert scene.page.preset_value() == SECOND_PRESET_NAME
    assert arrived
    assert scene.page.responses()[0]["status"] == 202
    job_id = scene.page.stored_results()[0]["job_id"]
    assert scene.api.get_job(job_id).json()["state"] in ("queued", "running")
    # 起こし終えた後の補正の控えに、選んだプリセットの名前が残る
    scene.stub.release.set()
    assert wait_for(lambda: corrected == [SECOND_PRESET_NAME])


def test_error_when_glossary_preset_not_found(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """選んだ後に設定から削除されたプリセットで MP3 のファイルを送信すると 400 で返り、選択したプリセットが見つからないことが画面に出る。選択欄は取得し直した一覧になり、既定が選ばれる（異常シナリオ（一覧に無いプリセット））。"""
    # 準備: 用語集のプリセットが 2 つある画面で 2 つ目を選んだ後に、設定から 2 つ目のプリセットを削除する
    scene = build_scene(
        start_inprocess,
        open_edge,
        tmp_path,
        monkeypatch,
        stub_text=STUB_TEXT,
        settings=make_glossary_preset_settings(tmp_path),
    )
    assert wait_for(lambda: len(scene.page.preset_options()) == PRESET_OPTION_COUNT)
    scene.page.select_preset(SECOND_PRESET_NAME)
    store = scene.app.handlers.settings_store
    current = store.get()
    store.replace(
        current.model_copy(
            update={
                "glossary_presets": [
                    preset for preset in current.glossary_presets if preset.name != SECOND_PRESET_NAME
                ]
            }
        )
    )
    scene.page.record_requests()
    # 実行
    scene.page.choose_file(encode_audio(scene.speech_wav, "mp3"), "speech.mp3", "audio/mpeg")
    arrived = wait_for(lambda: len(scene.page.responses()) == 1)
    shown = wait_for(lambda: scene.page.preset_not_found_error() is not None)
    reset = wait_for(lambda: len(scene.page.preset_options()) == PRESET_OPTION_COUNT - 1)
    # 検証
    assert arrived
    response = scene.page.responses()[0]
    assert response["status"] == 400
    assert "problem+json" in response["content_type"]
    assert "job_id" not in response["body"]
    assert shown
    error = scene.page.preset_not_found_error()
    assert error is not None
    assert error[0] == PRESET_NOT_FOUND_TITLE
    assert SECOND_PRESET_NAME in error[1]
    assert scene.page.results() == []
    assert scene.app.web_temp_files() == []
    assert reset
    assert scene.page.preset_options() == [
        ("", f"設定に従う（{FIRST_PRESET_NAME}）"),
        (FIRST_PRESET_NAME, FIRST_PRESET_NAME),
    ]
    assert scene.page.preset_value() == ""
