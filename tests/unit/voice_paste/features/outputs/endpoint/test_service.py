"""features/outputs/endpoint/service.py（deliver_to_endpoint）の単体テスト。

POST（post）とタイムアウトを返す関数（get_timeout_sec）は Mock にして、送る中身・ヘッダー・回数を確かめる。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome

if TYPE_CHECKING:
    from voice_paste.integrations.http.types import PostResult
    from voice_paste.shared.settings import EndpointPreset

URL = "http://127.0.0.1:9000/hook"
TIMEOUT_SEC = 1.5
AUTHORIZATION = "Bearer test-token"
PAYLOAD = {
    "session_id": "session-1",
    "result": "transcribed",
    "text": "てすと",
    "error": None,
}


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「てすと」）を作る。"""
    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )


def _preset(*, authorization: str = "") -> EndpointPreset:
    """URL が http://127.0.0.1:9000/hook のエンドポイントへ送るのプリセットを作る。"""
    from voice_paste.shared.settings import EndpointPreset

    return EndpointPreset(title="受け口", url=URL, authorization=authorization)


def _result(status: int) -> PostResult:
    """送り先の応答（ステータスだけ）を作る。"""
    from voice_paste.integrations.http.types import PostResult

    return PostResult(status=status, retry_after_sec=None)


def test_deliver_to_endpoint() -> None:
    """送る中身を 1 回送る（正常系）。"""
    from voice_paste.features.outputs.endpoint.service import deliver_to_endpoint

    # 準備
    post = MagicMock(return_value=_result(200))
    get_timeout_sec = MagicMock(return_value=TIMEOUT_SEC)

    # 実行
    deliver_to_endpoint(_outcome(), _preset(), post=post, get_timeout_sec=get_timeout_sec)

    # 検証
    post.assert_called_once_with(URL, PAYLOAD, TIMEOUT_SEC, {})


def test_deliver_to_endpoint_when_authorization(caplog: pytest.LogCaptureFixture) -> None:
    """Authorization を付けて送り、ログに書かない（正常系）。"""
    from voice_paste.features.outputs.endpoint.service import deliver_to_endpoint

    # 準備
    caplog.set_level(logging.DEBUG)
    post = MagicMock(return_value=_result(204))
    get_timeout_sec = MagicMock(return_value=TIMEOUT_SEC)

    # 実行
    deliver_to_endpoint(
        _outcome(),
        _preset(authorization=AUTHORIZATION),
        post=post,
        get_timeout_sec=get_timeout_sec,
    )

    # 検証
    post.assert_called_once_with(URL, PAYLOAD, TIMEOUT_SEC, {"Authorization": AUTHORIZATION})
    assert "test-token" not in caplog.text


def test_deliver_to_endpoint_when_error_status() -> None:
    """2xx 以外は送り直さず DeliveryError（異常系）。"""
    from voice_paste.features.outputs.endpoint.service import deliver_to_endpoint

    # 準備
    post = MagicMock(return_value=_result(500))
    get_timeout_sec = MagicMock(return_value=TIMEOUT_SEC)

    # 実行・検証
    with pytest.raises(DeliveryError):
        deliver_to_endpoint(_outcome(), _preset(), post=post, get_timeout_sec=get_timeout_sec)
    assert post.call_count == 1


def test_deliver_to_endpoint_when_unreachable() -> None:
    """届かなければ送り直さず DeliveryError（異常系）。"""
    from voice_paste.features.outputs.endpoint.service import deliver_to_endpoint

    # 準備
    post = MagicMock(side_effect=DeliveryError("接続できない"))
    get_timeout_sec = MagicMock(return_value=TIMEOUT_SEC)

    # 実行・検証
    with pytest.raises(DeliveryError):
        deliver_to_endpoint(_outcome(), _preset(), post=post, get_timeout_sec=get_timeout_sec)
    assert post.call_count == 1
