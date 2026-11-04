"""単一ユースケース「ブラウザで結果を受け取る」の E2E テスト。

常駐アプリは pytest のプロセスの中で `build_handlers` で配線し、API は 127.0.0.1 の空きポートで待ち受ける（起動・トレイ・ホットキーの受付は通さない）。
画面は Windows の Edge を headless で起動し、DevTools Protocol で `http://localhost:{ポート}/web/` を操作する（localhost の Origin は許す Origin に入れる）。
Edge のマイクは偽物で、Windows の音声合成（SAPI）で書き出した WAV を流す。
文字起こしのエンジンは、決めた文を返す（途中の進みを知らせる・放すまで待つ・失敗する）関数に差し替える。
端末の保存（localStorage・IndexedDB）は、画面を開いたオリジンの中を JS で読み書きする。
実機の Windows と Edge が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.support.browser import BrowserPage, wait_for
from tests.support.inprocess import (
    encode_audio,
    make_settings,
    requires_web_transcription,
    silence_input,
)
from tests.support.web_scene import STUB_TEXT, OpenEdge, StartInProcess, WebScene, build_scene, record_for
from voice_paste.integrations.openai.credentials import OPENAI_API_KEY_ENV
from voice_paste.shared.errors import TranscriptionError

pytestmark = [pytest.mark.real_machine, requires_web_transcription]

RECORD_SEC = 2
"""画面で録る長さ（秒）。"""

POLL_WAIT_SEC = 6.0
"""取りに行く間隔（2 秒）を 3 回分越えて待つ長さ。"""

RETENTION_DAYS = 7
"""端末に残す期間（日）。"""

RESULT_LIMIT = 10
"""端末に残す結果の件数。"""

WRONG_TEXT = "きめたぶんです"
"""文字起こしが返す、用語集で補正される前の文。"""

CORRECTED_TEXT = "決めた文です"
"""用語集で補正した後の文。"""

GLOSSARY_ROWS = "誤変換,正しい表記\nきめたぶん,決めた文\n"
"""用語集の CSV。"""

TRANSCRIPTION_ERROR_TEXT = "文字起こしに失敗させた"
"""差し替えた文字起こしが送出する例外のメッセージ。"""

OPENAI_TEST_API_KEY = "sk-test-not-sent"
"""OpenAI API のエンジンを組み立てるためだけに環境変数で渡す、テスト用の API キー（文字起こしは差し替えるため送信しない）。"""


def _stored(job_id: str, text: str, sent_at: datetime) -> dict[str, Any]:
    """localStorage に残す、文字起こしの終わった結果 1 件。"""
    return {
        "job_id": job_id,
        "state": "done",
        "source": "画面録音",
        "duration_sec": 3,
        "sent_at": sent_at.isoformat(),
        "text": text,
    }


def _send_file(scene: WebScene) -> None:
    """MP3 のファイルを選んで送信し、結果の一覧に件が出るまで待つ。"""
    scene.page.choose_file(encode_audio(scene.speech_wav, "mp3"), "speech.mp3", "audio/mpeg")
    assert wait_for(lambda: len(scene.page.results()) >= 1)


def _put_glossary(tmp_path: Path) -> None:
    """設定のフォルダに、用語集の CSV を置く。"""
    (tmp_path / "yogo.csv").write_text(GLOSSARY_ROWS, encoding="utf-8")


def _first_text(page: BrowserPage) -> str:
    """結果の一覧の先頭の件の文字を返す。"""
    results = page.results()
    return str(results[0]["text"]) if results else ""


def test_normal(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """待ちの間は件に進み具合が出て、終わると用語集で補正した文字が出る。結果が端末に残り、コピーでクリップボードに入る（正常系）。"""
    # 準備
    _put_glossary(tmp_path)
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=WRONG_TEXT)
    assert scene.stub is not None
    scene.stub.progress_points = [0.4, 0.8]
    scene.stub.hold()
    scene.page.watch_clipboard()
    # 実行
    _send_file(scene)
    running = wait_for(
        lambda: scene.page.results()[0]["status"] == "文字起こし中"
        and scene.page.results()[0]["percent"] == "80%"
    )
    scene.stub.release.set()
    done = wait_for(lambda: _first_text(scene.page) == CORRECTED_TEXT)
    scene.page.click("copy_button")
    # 検証
    assert running
    assert done
    stored = scene.page.stored_results()
    assert len(stored) == 1
    assert stored[0]["state"] == "done"
    assert stored[0]["text"] == CORRECTED_TEXT
    assert stored[0]["sent_at"]
    assert wait_for(lambda: scene.page.copied_text() == CORRECTED_TEXT)


def test_normal_when_engine_reports_no_progress(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """進みを返さないエンジン（OpenAI API）では、待ちの間は件に「文字起こし中」だけが出て % と進みのバーが出ず、終わると起こした文字が出る（正常系）。"""
    # 準備: OpenAI API のエンジンで立て、文字起こしは進みを知らせずに放すまで待つ
    monkeypatch.setenv(OPENAI_API_KEY_ENV, OPENAI_TEST_API_KEY)
    settings = make_settings(only_paste_and_send=True)
    transcription = settings.transcription.model_copy(update={"engine": "openai"})
    settings = settings.model_copy(update={"transcription": transcription})
    scene = build_scene(
        start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT, settings=settings
    )
    assert scene.stub is not None
    scene.stub.hold()
    # 実行
    _send_file(scene)
    running = wait_for(lambda: scene.page.results()[0]["status"] == "文字起こし中")
    shown = scene.page.results()[0]
    scene.stub.release.set()
    done = wait_for(lambda: _first_text(scene.page) == STUB_TEXT)
    # 検証
    assert running
    assert shown["percent"] == ""
    assert shown["progress_shown"] is False
    assert done


def test_normal_when_delete_result(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端末に結果が 2 件ある画面で、確認を経て 1 件を削除すると、一覧と端末からその 1 件だけが消え、もう 1 件は残る（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    now = datetime.now(UTC)
    scene.page.seed_results([_stored("newer", "新しい件", now), _stored("older", "古い件", now)])
    assert scene.page.reload()
    assert len(scene.page.results()) == 2
    # 実行
    scene.page.click("delete_button")
    assert scene.page.wait_until("document.getElementById('delete-dialog').open")
    scene.page.click("delete_confirm")
    # 検証
    assert wait_for(lambda: len(scene.page.results()) == 1)
    assert _first_text(scene.page) == "古い件"
    assert [item["job_id"] for item in scene.page.stored_results()] == ["older"]


def test_normal_when_over_result_limit(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端末に結果が 10 件ある画面で新しい結果を受けると、10 件のまま新しい件が先頭に来て、いちばん古い件が消える（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    now = datetime.now(UTC)
    scene.page.seed_results([_stored(f"kept{index}", f"件{index}", now) for index in range(RESULT_LIMIT)])
    assert scene.page.reload()
    # 実行
    scene.page.choose_file(encode_audio(scene.speech_wav, "mp3"), "speech.mp3", "audio/mpeg")
    done = wait_for(lambda: _first_text(scene.page) == STUB_TEXT)
    # 検証
    assert done
    stored = scene.page.stored_results()
    assert len(stored) == RESULT_LIMIT
    assert stored[0]["text"] == STUB_TEXT
    assert "kept9" not in [item["job_id"] for item in stored]
    assert "kept8" in [item["job_id"] for item in stored]


def test_normal_when_expired(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存日時が期限（7 日）より前の結果と音声がある端末で画面を開くと、期限を過ぎたものが消え、期限内の結果は一覧に出る（正常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    now = datetime.now(UTC)
    expired_at = now - timedelta(days=RETENTION_DAYS, hours=1)
    scene.page.seed_results([_stored("fresh", "期限内の件", now), _stored("stale", "期限切れの件", expired_at)])
    scene.page.seed_kept_audio(recorded_at=expired_at.isoformat(), state="sent", job_id=None)
    assert scene.page.kept_audio() is not None
    # 実行
    assert scene.page.reload()
    # 検証
    assert wait_for(lambda: scene.page.kept_audio() is None)
    assert [item["job_id"] for item in scene.page.stored_results()] == ["fresh"]
    assert [item["text"] for item in scene.page.results()] == ["期限内の件"]


def test_error_when_transcription_failed(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画面で録った音声の文字起こしが失敗すると、件に失敗が出る。端末の音声は残り、再送できる。失敗した件は端末に残らない（異常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    assert scene.stub is not None
    scene.stub.error = TranscriptionError(TRANSCRIPTION_ERROR_TEXT)
    # 実行
    record_for(scene.page, RECORD_SEC)
    failed = wait_for(
        lambda: bool(scene.page.results()) and scene.page.results()[0]["status"] == "文字起こし失敗"
    )
    # 検証
    assert failed
    assert TRANSCRIPTION_ERROR_TEXT in scene.page.results()[0]["detail"]
    kept = scene.page.kept_audio()
    assert kept is not None
    assert wait_for(lambda: scene.page.kept_state() == "文字起こし前")
    assert not scene.page.is_disabled("resend_button")
    assert scene.page.is_visible("resend_button")
    assert not scene.page.is_disabled("download_button")
    assert scene.page.stored_results() == []


def test_error_when_job_not_found(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ジョブを受け付けた後に常駐アプリを起動し直して結果を取りに行くと 404 で返り、件に結果が見つからないことが出て取りに行くのをやめる（異常系）。"""
    # 準備
    scene = build_scene(start_inprocess, open_edge, tmp_path, monkeypatch, stub_text=STUB_TEXT)
    assert scene.stub is not None
    scene.stub.hold()
    record_for(scene.page, RECORD_SEC)
    assert wait_for(lambda: len(scene.page.results()) == 1)
    scene.page.record_fetches()
    port = scene.api.port
    scene.api.close()
    restarted = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    restarted.start_web_api(port=port)
    # 実行
    gone = wait_for(lambda: scene.page.results()[0]["status"] == "結果消失")
    polled = len(scene.page.fetches())
    scene.stub.release.set()
    # 検証
    assert gone
    assert scene.page.fetches()[-1]["status"] == 404
    assert "problem+json" in scene.page.fetches()[-1]["content_type"]
    assert scene.page.kept_audio() is not None
    assert not scene.page.is_disabled("resend_button")
    # 取りに行く間隔を数回越えて待っても、取りに行く回数が増えない
    assert not wait_for(lambda: len(scene.page.fetches()) > polled, POLL_WAIT_SEC)
