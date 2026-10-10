"""features/outputs/callback/service.py（is_callback_allowed・deliver_to_caller・inject_callback）の単体テスト。

POST（post）・間を置く関数（sleep）・乱数（jitter）は Mock にして、再送の回数と待ちを確かめる。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from tests.unit.voice_paste.features.outputs.helpers import make_output_deps
from voice_paste.shared.errors import DeliveryError

TARGET = "http://127.0.0.1:9000/result"
RETRY_COUNT = 2
RETRY_BASE_SEC = 1.0


def _outcome() -> object:
    """届ける結果（起こした文字「てすと」）を作る。"""
    from voice_paste.shared.types import TranscriptionOutcome

    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )


def _segment_outcome(segment_number: int) -> object:
    """連続録音の区間（起こした文字「てすと」・通し番号つき）の結果を作る。"""
    from voice_paste.shared.types import TranscriptionOutcome

    return TranscriptionOutcome(
        session_id="session-1",
        result="transcribed",
        text="てすと",
        error=None,
        segment_number=segment_number,
    )


def _result(status: int, retry_after_sec: float | None = None) -> object:
    """返送先の応答（ステータスと Retry-After の秒数）を作る。"""
    from voice_paste.integrations.http.types import PostResult

    return PostResult(status=status, retry_after_sec=retry_after_sec)


def _identity_jitter() -> MagicMock:
    """受けた値をそのまま返す jitter の Mock を作る。"""
    return MagicMock(side_effect=lambda upper: upper)


def _deliver(
    post: MagicMock,
    sleep: MagicMock,
    jitter: MagicMock,
    target: str = TARGET,
    outcome: object | None = None,
) -> None:
    """deliver_to_caller を、再送回数 2・間隔の基数 1.0 秒・許可ホスト無しで呼ぶ（結果を渡さなければ起こした文字の結果）。"""
    from voice_paste.features.outputs.callback.service import deliver_to_caller

    deliver_to_caller(
        _outcome() if outcome is None else outcome,
        target,
        post=post,
        allowed_hosts=frozenset(),
        retry_count=RETRY_COUNT,
        retry_base_sec=RETRY_BASE_SEC,
        sleep=sleep,
        jitter=jitter,
    )


def _error_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """ERROR のログを返す。"""
    return [record for record in caplog.records if record.levelno == logging.ERROR]


# === is_callback_allowed ===


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://127.0.0.1:9000/x", id="ipv4"),
        pytest.param("http://localhost/x", id="localhost"),
        pytest.param("http://[::1]/x", id="ipv6"),
    ],
)
def test_is_callback_allowed_when_loopback(url: str) -> None:
    """loopback は許す（正常系）。"""
    from voice_paste.features.outputs.callback.service import is_callback_allowed

    # 実行
    allowed = is_callback_allowed(url, frozenset())

    # 検証
    assert allowed is True


def test_is_callback_allowed_when_allowed_host() -> None:
    """許可したホストは許す（正常系）。"""
    from voice_paste.features.outputs.callback.service import is_callback_allowed

    # 実行
    allowed = is_callback_allowed("http://tools.example/x", frozenset({"tools.example"}))

    # 検証
    assert allowed is True


def test_is_callback_allowed_when_other_host() -> None:
    """それ以外は許さない（正常系）。"""
    from voice_paste.features.outputs.callback.service import is_callback_allowed

    # 実行
    allowed = is_callback_allowed("http://example.com/x", frozenset())

    # 検証
    assert allowed is False


# === deliver_to_caller ===


def test_deliver_to_caller() -> None:
    """1 回で届く（正常系）。"""
    # 準備
    post = MagicMock(return_value=_result(200))
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    post.assert_called_once_with(
        TARGET,
        {
            "session_id": "session-1",
            "result": "transcribed",
            "text": "てすと",
            "error": None,
            "segment_number": None,
            "segment_count": None,
        },
    )
    sleep.assert_not_called()


def test_deliver_to_caller_when_segment() -> None:
    """連続録音の区間は通し番号を付けて送る（正常系）。"""
    # 準備
    post = MagicMock(return_value=_result(200))
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter, outcome=_segment_outcome(3))

    # 検証
    post.assert_called_once_with(
        TARGET,
        {
            "session_id": "session-1",
            "result": "transcribed",
            "text": "てすと",
            "error": None,
            "segment_number": 3,
            "segment_count": None,
        },
    )


def test_deliver_to_caller_when_retry_succeeds() -> None:
    """再送で届く（正常系）。"""
    # 準備
    post = MagicMock(side_effect=[_result(500), DeliveryError("タイムアウト"), _result(200)])
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    assert post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


def test_deliver_to_caller_when_retry_after() -> None:
    """Retry-After に従う（正常系）。"""
    # 準備
    post = MagicMock(side_effect=[_result(429, retry_after_sec=1.5), _result(200)])
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    sleep.assert_called_once_with(1.5)
    jitter.assert_not_called()
    assert post.call_count == 2


def test_deliver_to_caller_when_retry_after_too_long(caplog: pytest.LogCaptureFixture) -> None:
    """待ちの上限を超える Retry-After は待たずに終える（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    post = MagicMock(return_value=_result(503, retry_after_sec=60.0))
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    assert post.call_count == 1
    sleep.assert_not_called()
    assert len(_error_logs(caplog)) == 1


def test_deliver_to_caller_when_client_error(caplog: pytest.LogCaptureFixture) -> None:
    """送り直しても変わらない 4xx は再送しない（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    post = MagicMock(return_value=_result(404))
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    assert post.call_count == 1
    sleep.assert_not_called()
    assert len(_error_logs(caplog)) == 1


def test_deliver_to_caller_when_unreachable(caplog: pytest.LogCaptureFixture) -> None:
    """届かなければログに書いて終える（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    post = MagicMock(return_value=_result(500))
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行
    _deliver(post, sleep, jitter)

    # 検証
    assert post.call_count == 3
    assert sleep.call_count == 2
    assert len(_error_logs(caplog)) == 1


def test_deliver_to_caller_when_not_allowed() -> None:
    """許されない返送先へは送らない（異常系）。"""
    # 準備
    post = MagicMock()
    sleep = MagicMock()
    jitter = _identity_jitter()

    # 実行・検証
    with pytest.raises(DeliveryError):
        _deliver(post, sleep, jitter, target="http://example.com/x")
    post.assert_not_called()


# === inject_callback ===


def test_inject_callback() -> None:
    """返送の決定値と設定の許可ホストを渡す（正常系）。"""
    from voice_paste.features.outputs.callback.service import inject_callback
    from voice_paste.shared.settings import ApiSettings, Settings

    # 準備
    deps = make_output_deps(
        get_settings=MagicMock(
            return_value=Settings(api=ApiSettings(allowed_callback_hosts=["host.local"]))
        )
    )

    # 実行
    injected = inject_callback(deps)
    injected["post"]("http://host.local/x", {"text": "テスト"})

    # 検証
    assert set(injected) == {
        "post",
        "allowed_hosts",
        "retry_count",
        "retry_base_sec",
        "sleep",
        "jitter",
    }
    assert injected["allowed_hosts"] == frozenset({"host.local"})
    assert injected["retry_count"] == 3
    assert injected["retry_base_sec"] == 1.0
    assert injected["sleep"] is deps.sleep
    assert injected["jitter"] is deps.jitter
    deps.post.assert_called_once_with("http://host.local/x", {"text": "テスト"}, timeout_sec=1.5)
