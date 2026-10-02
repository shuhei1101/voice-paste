"""ホットキーのセッションが、確定で選んだ出力先へ届ける結合テスト。

SessionManager でホットキーのセッションを始めて確定し、main.py の配線（_wire_outputs）で作った出力先へ届くことを確かめる。
マイク・システム音量・文字起こしのエンジンと、キーボード・ブラウザのアダプタ（copy_to_clipboard・send_paste・send_enter・open_app_window）・間（time.sleep）は偽物。
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import call

from tests.integration.helpers import OutputStack
from voice_paste.shared.settings import (
    AiChatSettings,
    CopyOnlySettings,
    PasteAndSendSettings,
    PasteOnlySettings,
    Settings,
)

AI_CHAT_URL = "https://chatgpt.com"


def test_normal_when_paste_and_send(output_stack: Callable[[Settings | None], OutputStack]) -> None:
    """貼り付けて送信を選んで確定すると、コピー・貼り付け・待ち・Enter の順に届く（正常系）。"""
    # 準備
    stack = output_stack(None)

    # 実行
    stack.confirm("paste_and_send")

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.send_paste("<ctrl>+v"),
        call.sleep(0.5),
        call.send_enter(),
    ]
    assert "delivery_failed" not in stack.events()


def test_normal_when_ai_chat(output_stack: Callable[[Settings | None], OutputStack]) -> None:
    """送り先を付けて AI チャットを選んで確定すると、その送り先を開いて貼り付けて送る（正常系）。"""
    # 準備
    stack = output_stack(None)

    # 実行
    stack.confirm("ai_chat", AI_CHAT_URL)

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.open_app_window(AI_CHAT_URL),
        call.sleep(3.0),
        call.send_paste("<ctrl>+v"),
        call.sleep(0.5),
        call.send_enter(),
    ]
    assert "delivery_failed" not in stack.events()


def test_error_when_output_disabled(output_stack: Callable[[Settings | None], OutputStack]) -> None:
    """設定でオフの出力先を選んで確定すると、届けずに delivery_failed を知らせて待機中に戻る（異常系）。"""
    # 準備
    settings = Settings(
        outputs=[
            PasteAndSendSettings(),
            PasteOnlySettings(),
            CopyOnlySettings(),
            AiChatSettings(enabled=False),
        ]
    )
    stack = output_stack(settings)

    # 実行
    stack.confirm("ai_chat", AI_CHAT_URL)

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == []
    assert "delivery_failed" in stack.events()
