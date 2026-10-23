"""ブラウザの本文の上限（web_body_limit）の非機能要件テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、`build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて、
上限（100,000,000 バイト）の前後の大きさの本文を `POST /web/transcriptions` で送る。
本文は multipart の境界とヘッダーを含めてちょうどの大きさにする。文字起こしのエンジンは決めた文を返す関数に差し替える。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import make_audio
from tests.support.fixtures import start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import InProcessApp, make_settings, silence_input, stub_transcription
from tests.support.web_body import sized_multipart_body

pytestmark = pytest.mark.real_machine

BODY_LIMIT_BYTES = 100_000_000
"""ブラウザの本文の上限（バイト。これ未満を受け付ける）。"""

STUB_TEXT = "決めた文です"
"""文字起こしを差し替えたときに返す文。"""


def _start(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> InProcessApp:
    """文字起こしを決めた文を返す関数に差し替えて配線し、`/web/` を待ち受けさせる。"""
    stub_transcription(monkeypatch, STUB_TEXT)
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=silence_input(tmp_path)
    )
    app.start_web_api()
    return app


def _temp_files(app: InProcessApp) -> list[Path]:
    """ブラウザの音声の一時のフォルダに残っているファイルを返す。"""
    tmp_dir = app.handlers.web_api.tmp_dir
    return sorted(tmp_dir.iterdir()) if tmp_dir.exists() else []


def test_web_body_limit_when_under(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上限より 1 バイト小さい本文を受け付ける（実機）。"""
    # 準備
    app = _start(start_inprocess, tmp_path, monkeypatch)
    assert app.api is not None
    body = sized_multipart_body(make_audio("webm", tmp_path), BODY_LIMIT_BYTES - 1)

    # 実行
    response = app.api.post_web_body(body)

    # 検証
    assert len(body) == BODY_LIMIT_BYTES - 1
    assert response.status_code == 202


@pytest.mark.parametrize("chunked", [False, True], ids=["content_length", "chunked"])
def test_web_body_limit_when_at_limit(
    start_inprocess: Callable[..., InProcessApp],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chunked: bool,
) -> None:
    """上限ちょうどの本文を、Content-Length を付けても付けずに chunked で送っても断り、一時のファイルを残さない（実機）。"""
    # 準備
    app = _start(start_inprocess, tmp_path, monkeypatch)
    assert app.api is not None
    body = sized_multipart_body(make_audio("webm", tmp_path), BODY_LIMIT_BYTES)

    # 実行
    response = app.api.post_web_body(body, chunked=chunked)

    # 検証
    assert len(body) == BODY_LIMIT_BYTES
    assert response.status_code == 413
    assert "problem+json" in response.headers["content-type"]
    assert _temp_files(app) == []
