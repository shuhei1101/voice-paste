"""設定のエンドポイントへ送る（カスタムプリセットの届け先へ POST）の結合テスト。

SessionManager でホットキーのセッションを始め、エンドポイントへ送るのプリセットを選んで確定し、
main.py の配線（_wire_preset_kinds）で作った送り先へ届くことを、127.0.0.1 のテスト用の受け口で確かめる。
マイク・システム音量・文字起こしのエンジンと、キーボード・ブラウザのアダプタ・間は偽物。送りは本物の httpx。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from tests.integration.helpers import CallbackReceiver, OutputStack
from tests.support.fixtures import receiver  # noqa: F401 フィクスチャとして使う
from voice_paste.shared.settings import EndpointPreset, Settings

AUTHORIZATION = "Bearer test-token"
"""プリセットに持たせる Authorization の値。ログに書かれてはいけない。"""

PAYLOAD_TEXT = "てすと"
"""偽物のエンジンが返す起こした文字。"""


def _preset(receiver: CallbackReceiver, authorization: str = "") -> EndpointPreset:
    """URL がテスト用の受け口のエンドポイントへ送るのプリセットを作る。"""
    return EndpointPreset(title="受け口", url=receiver.url, authorization=authorization)


def test_normal(
    output_stack: Callable[[Settings | None], OutputStack], receiver: CallbackReceiver
) -> None:
    """起こした文字を送り先へ送る（正常系）。"""
    # 準備
    preset = _preset(receiver)
    stack = output_stack(Settings(presets=[preset]))

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert len(receiver.received) == 1
    payload = receiver.received[0]
    assert payload["result"] == "transcribed"
    assert payload["text"] == PAYLOAD_TEXT
    assert payload["error"] is None
    assert "authorization" not in receiver.headers[0]
    assert "delivery_failed" not in stack.events()


def test_normal_when_authorization_set(
    output_stack: Callable[[Settings | None], OutputStack],
    receiver: CallbackReceiver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """プリセットの Authorization の値を、ヘッダーに入れて送る（正常系）。"""
    # 準備
    caplog.set_level(logging.DEBUG)
    preset = _preset(receiver, AUTHORIZATION)
    stack = output_stack(Settings(presets=[preset]))

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert len(receiver.received) == 1
    assert receiver.headers[0]["authorization"] == AUTHORIZATION
    assert "test-token" not in caplog.text


def test_error_when_endpoint_unreachable(
    output_stack: Callable[[Settings | None], OutputStack], receiver: CallbackReceiver
) -> None:
    """2xx 以外なら送り直さず、届けられなかったことを知らせて待機中に戻る（異常系）。"""
    # 準備
    receiver.default_status = 500
    preset = _preset(receiver)
    stack = output_stack(Settings(presets=[preset]))

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert len(receiver.received) == 1
    assert "delivery_failed" in stack.events()
