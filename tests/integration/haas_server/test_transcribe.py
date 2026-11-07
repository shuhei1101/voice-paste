"""音声を文字に起こす（POST /transcriptions）の結合テスト。

Haas のモデルは偽物に差し替える（GPU を使わない）。
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from haas_server.app import TranscribeOptions
from tests.integration.haas_server.helpers import (
    FAKE_TEXT,
    MODEL_RATE,
    TOLERANCE_SAMPLES,
    FakeModel,
    make_wav,
    make_webm,
)

SHORT_SECONDS = 3
LONG_SECONDS = 40
TUNING_SECONDS = 25


def _post(
    client: TestClient,
    audio: bytes,
    *,
    vocabulary: str | None = None,
    tuning: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """音声と手がかりと調整の値を multipart で送信する。"""
    data = ({} if vocabulary is None else {"vocabulary": vocabulary}) | (tuning or {})
    return client.post(
        "/transcriptions", files={"audio": ("audio", audio)}, data=data, headers=headers
    )


def test_normal(client: TestClient, model: FakeModel) -> None:
    """短い WAV を、読みのある単語と読みの無い単語の手がかりつきで起こす（正常系）。"""
    # 準備
    vocabulary = json.dumps(
        [{"written": "突合", "reading": "とつごう"}, {"written": "voice-paste", "reading": None}]
    )

    # 実行
    response = _post(client, make_wav(SHORT_SECONDS), vocabulary=vocabulary)

    # 検証
    assert response.status_code == 200
    assert response.json() == {"text": FAKE_TEXT}
    assert model.samples[0].ndim == 1
    assert abs(len(model.samples[0]) - MODEL_RATE * SHORT_SECONDS) < TOLERANCE_SAMPLES
    assert model.vocabularies == [{"突合": ["とつごう"], "voice-paste": []}]
    assert model.longform_calls == 0


def test_normal_when_longer_than_30_seconds(client: TestClient, model: FakeModel) -> None:
    """30 秒を超える音声を静かな箇所で区切って起こす（正常系）。"""
    # 実行
    response = _post(client, make_wav(LONG_SECONDS))

    # 検証
    assert response.status_code == 200
    assert response.json() == {"text": FAKE_TEXT}
    assert model.longform_calls == 1
    assert len(model.samples) == 1


def test_normal_when_no_vocabulary(client: TestClient, model: FakeModel) -> None:
    """vocabulary を付けない要求は、手がかりを指定せずに起こす（正常系）。"""
    # 実行
    response = _post(client, make_wav(SHORT_SECONDS))

    # 検証
    assert response.status_code == 200
    assert model.vocabularies == [None]


def test_normal_when_browser_audio(client: TestClient, model: FakeModel) -> None:
    """ブラウザが録った webm の音声を復号して起こす（正常系）。"""
    # 実行
    response = _post(client, make_webm(SHORT_SECONDS))

    # 検証
    assert response.status_code == 200
    assert response.json() == {"text": FAKE_TEXT}
    assert abs(len(model.samples[0]) - MODEL_RATE * SHORT_SECONDS) < TOLERANCE_SAMPLES


def test_error_when_audio_unreadable(client: TestClient, model: FakeModel) -> None:
    """音声として読めないファイルを断る（異常系）。"""
    # 実行
    response = _post(client, "音声ではない".encode())

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "音声を読めない" in response.json()["detail"]
    assert model.samples == []


@pytest.mark.parametrize(
    "vocabulary",
    [
        pytest.param('[{"written": "", "reading": "から"}]', id="empty_written"),
        pytest.param('{"written": "突合"}', id="not_array"),
        pytest.param("not json", id="not_json"),
    ],
)
def test_error_when_vocabulary_invalid(
    client: TestClient, model: FakeModel, vocabulary: str
) -> None:
    """vocabulary が JSON の配列でないか、written が空の要素がある要求を断る（異常系）。"""
    # 実行
    response = _post(client, make_wav(SHORT_SECONDS), vocabulary=vocabulary)

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "手がかり" in response.json()["detail"]
    assert model.samples == []


def test_error_when_transcription_failed(
    client: TestClient, model: FakeModel, caplog: pytest.LogCaptureFixture
) -> None:
    """モデルが例外を送出したら 500 を返し、次の要求は受け付ける（異常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    model.errors.append(RuntimeError("GPU のメモリが足りない"))

    # 実行
    failed = _post(client, make_wav(SHORT_SECONDS))
    succeeded = _post(client, make_wav(SHORT_SECONDS))

    # 検証
    assert failed.status_code == 500
    assert failed.headers["content-type"].startswith("application/problem+json")
    assert "GPU のメモリが足りない" in failed.json()["detail"]
    assert succeeded.status_code == 200
    assert succeeded.json() == {"text": FAKE_TEXT}
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"Host": "evil.example:47824"}, id="host"),
        pytest.param({"Origin": "http://evil.example"}, id="origin"),
    ],
)
def test_error_when_origin_not_allowed(
    client: TestClient,
    model: FakeModel,
    caplog: pytest.LogCaptureFixture,
    headers: dict[str, str],
) -> None:
    """Host が合わない要求と、Origin が付いた要求を、起こさずに断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    response = _post(client, make_wav(SHORT_SECONDS), headers=headers)

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert model.samples == []
    assert "evil.example" in caplog.text


def test_normal_when_tuning_values(client: TestClient, model: FakeModel) -> None:
    """要求の調整の値を、起こし方の選択と haas_asr の引数に使用する（正常系）。"""
    # 準備
    vocabulary = json.dumps([{"written": "突合", "reading": "とつごう"}])
    tuning = {
        "short_audio_limit_sec": "20",
        "batch_size": "8",
        "alpha": "3.0",
        "guard": "false",
        "chunk_sec": "15",
        "search_sec": "1",
        "window_sec": "0.05",
        "separator": "。",
    }

    # 実行
    response = _post(client, make_wav(TUNING_SECONDS), vocabulary=vocabulary, tuning=tuning)

    # 検証
    assert response.status_code == 200
    assert response.json() == {"text": FAKE_TEXT}
    assert model.longform_calls == 1
    assert model.options == [
        TranscribeOptions(
            short_audio_limit_sec=20.0,
            batch_size=8,
            alpha=3.0,
            guard=False,
            chunk_sec=15.0,
            search_sec=1.0,
            window_sec=0.05,
            separator="。",
        )
    ]
    assert model.alphas == [3.0]


@pytest.mark.parametrize(
    ("tuning", "field"),
    [
        pytest.param({"batch_size": "0"}, "batch_size", id="batch_size_zero"),
        pytest.param({"guard": "yes"}, "guard", id="guard_yes"),
    ],
)
def test_error_when_tuning_value_invalid(
    client: TestClient,
    model: FakeModel,
    caplog: pytest.LogCaptureFixture,
    tuning: dict[str, str],
    field: str,
) -> None:
    """範囲の外か型の合わない調整の値を持つ要求を、起こさずに断る（異常系）。"""
    # 実行
    with caplog.at_level(logging.WARNING):
        response = _post(client, make_wav(SHORT_SECONDS), tuning=tuning)

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert field in response.json()["detail"]
    assert model.samples == []
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
