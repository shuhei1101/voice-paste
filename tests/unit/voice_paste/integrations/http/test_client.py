"""integrations/http/client.py（post_json）の単体テスト。

送り先は httpx.MockTransport に差し替える。
post_json が作る httpx.Client に MockTransport を渡すため、httpx.Client を同じ引数で作り直す関数へ差し替える。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from voice_paste.shared.errors import DeliveryError

URL = "http://127.0.0.1:9000/result"
PAYLOAD = {"session_id": "session-1", "result": "transcribed", "text": "てすと", "error": None}
TIMEOUT_SEC = 1.5


def _use_receiver(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """httpx.Client の通信を handler（送信先のエンドポイント）へ向け、エンドポイントに届いた要求を覚えるリストを返す。"""
    received: list[httpx.Request] = []
    real_client = httpx.Client

    def _handle(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return handler(request)

    def _client(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(_handle), **kwargs)

    monkeypatch.setattr(httpx, "Client", _client)
    return received


def _http_date(delta: timedelta) -> str:
    """今から delta ずらした時刻を、Retry-After に使う HTTP の日付の形にする。"""
    return format_datetime(datetime.now(UTC) + delta, usegmt=True)


def test_post_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON を送信してステータスを返す（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    received = _use_receiver(monkeypatch, lambda request: httpx.Response(204))

    # 実行
    result = post_json(URL, PAYLOAD, TIMEOUT_SEC)

    # 検証
    assert result.status == 204
    assert result.retry_after_sec is None
    assert received[0].headers["content-type"] == "application/json"
    assert json.loads(received[0].content) == PAYLOAD


def test_post_json_when_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """渡したヘッダーを付けて送信する（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    received = _use_receiver(monkeypatch, lambda request: httpx.Response(204))

    # 実行
    post_json(URL, PAYLOAD, TIMEOUT_SEC, {"Authorization": "Bearer test-token"})

    # 検証
    assert received[0].headers["authorization"] == "Bearer test-token"


def test_post_json_when_retry_after_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """秒数の Retry-After を返す（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    _use_receiver(monkeypatch, lambda request: httpx.Response(429, headers={"Retry-After": "3"}))

    # 実行
    result = post_json(URL, PAYLOAD, TIMEOUT_SEC)

    # 検証
    assert result.status == 429
    assert result.retry_after_sec == 3.0


def test_post_json_when_retry_after_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """読めない Retry-After は None（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    _use_receiver(
        monkeypatch, lambda request: httpx.Response(503, headers={"Retry-After": "soon"})
    )

    # 実行
    result = post_json(URL, PAYLOAD, TIMEOUT_SEC)

    # 検証
    assert result.status == 503
    assert result.retry_after_sec is None


def test_post_json_when_retry_after_past_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """過去の日付の Retry-After は 0（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    one_minute_ago = _http_date(timedelta(minutes=-1))
    _use_receiver(
        monkeypatch,
        lambda request: httpx.Response(503, headers={"Retry-After": one_minute_ago}),
    )

    # 実行
    result = post_json(URL, PAYLOAD, TIMEOUT_SEC)

    # 検証
    assert result.status == 503
    assert result.retry_after_sec == 0.0


def test_post_json_when_redirected(monkeypatch: pytest.MonkeyPatch) -> None:
    """リダイレクトを追わない（正常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    received = _use_receiver(
        monkeypatch,
        lambda request: httpx.Response(307, headers={"Location": "http://other.example/result"}),
    )

    # 実行
    result = post_json(URL, PAYLOAD, TIMEOUT_SEC)

    # 検証
    assert result.status == 307
    assert [request.url.host for request in received] == ["127.0.0.1"]


def test_post_json_when_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """タイムアウトは DeliveryError（異常系）。"""
    from voice_paste.integrations.http.client import post_json

    # 準備
    def _raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("タイムアウト", request=request)

    _use_receiver(monkeypatch, _raise_timeout)

    # 実行・検証
    with pytest.raises(DeliveryError):
        post_json(URL, PAYLOAD, TIMEOUT_SEC)
