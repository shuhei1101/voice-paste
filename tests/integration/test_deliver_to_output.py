"""ホットキーのセッションが、確定で選んだ出力先・ブラウザ添付のプリセットへ届ける結合テスト。

SessionManager でホットキーのセッションを始めて確定し、main.py の配線（_wire_outputs）で作った出力先へ届くことを確かめる。
マイク・システム音量・文字起こしのエンジンと、キーボード・ブラウザのアダプタ（copy_to_clipboard・send_paste・send_enter・open_app_window）・間（time.sleep）は偽物。
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import call

from tests.integration.helpers import OutputStack
from voice_paste.main import SETTINGS_MODEL
from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
from voice_paste.shared.settings import BrowserPreset, BrowserPresetOptions, PresetOptions, Settings

CHAT_URL = "https://chatgpt.com"


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
        call.send_enter(()),
    ]
    assert "delivery_failed" not in stack.events()


def test_normal_when_enter_modifiers(
    output_stack: Callable[[Settings | None], OutputStack],
) -> None:
    """貼り付けて送信で Ctrl をオンにして確定すると、待った後に Ctrl を押したまま Enter を送る（正常系）。"""
    # 準備
    settings = SETTINGS_MODEL(
        outputs=[
            PasteAndSendSettings(enter_modifiers=["ctrl"]),
            PasteOnlySettings(),
            CopyOnlySettings(),
        ]
    )
    stack = output_stack(settings)

    # 実行
    stack.confirm("paste_and_send")

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.send_paste("<ctrl>+v"),
        call.sleep(0.5),
        call.send_enter(("ctrl",)),
    ]
    assert "delivery_failed" not in stack.events()


def test_normal_when_browser_preset(
    output_stack: Callable[[Settings | None], OutputStack],
) -> None:
    """ブラウザ添付のプリセットを選んで確定すると、その URL を開いて貼り付けて Enter まで送信する（正常系）。"""
    # 準備
    preset = BrowserPreset(title="ChatGPT", url=CHAT_URL)
    stack = output_stack(SETTINGS_MODEL(presets=[preset]))

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.open_app_window(CHAT_URL),
        call.sleep(3.0),
        call.send_paste("<ctrl>+v"),
        call.sleep(0.5),
        call.send_enter(),
    ]
    assert "delivery_failed" not in stack.events()


def test_normal_when_browser_preset_and_enter_modifiers(
    output_stack: Callable[[Settings | None], OutputStack],
) -> None:
    """貼り付けて送信で Ctrl をオンにしていても、ブラウザ添付のプリセットは修飾キーなしで Enter を送る（正常系）。"""
    # 準備
    preset = BrowserPreset(title="ChatGPT", url=CHAT_URL)
    settings = SETTINGS_MODEL(
        presets=[preset],
        outputs=[
            PasteAndSendSettings(enter_modifiers=["ctrl"]),
            PasteOnlySettings(),
            CopyOnlySettings(),
        ],
    )
    stack = output_stack(settings)

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.open_app_window(CHAT_URL),
        call.sleep(3.0),
        call.send_paste("<ctrl>+v"),
        call.sleep(0.5),
        call.send_enter(),
    ]
    assert "delivery_failed" not in stack.events()


def test_normal_when_browser_preset_without_enter(
    output_stack: Callable[[Settings | None], OutputStack],
) -> None:
    """Enter まで送らないブラウザ添付のプリセットを選んで確定すると、貼り付けで止まる（正常系）。"""
    # 準備
    preset = BrowserPreset(title="ChatGPT", url=CHAT_URL, send_enter=False)
    settings = SETTINGS_MODEL(
        presets=[preset],
        preset_options=PresetOptions(browser=BrowserPresetOptions(open_delay_sec=1.0)),
    )
    stack = output_stack(settings)

    # 実行
    stack.confirm(preset=preset)

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == [
        call.copy_to_clipboard("てすと"),
        call.open_app_window(CHAT_URL),
        call.sleep(1.0),
        call.send_paste("<ctrl>+v"),
    ]
    assert "delivery_failed" not in stack.events()


def test_error_when_output_disabled(output_stack: Callable[[Settings | None], OutputStack]) -> None:
    """設定でオフの出力先を選んで確定すると、届けずに delivery_failed を知らせて待機中に戻る（異常系）。"""
    # 準備
    settings = SETTINGS_MODEL(
        outputs=[PasteAndSendSettings(), PasteOnlySettings(), CopyOnlySettings(enabled=False)]
    )
    stack = output_stack(settings)

    # 実行
    stack.confirm("copy_only")

    # 検証
    assert stack.wait_for_idle()
    assert stack.adapters.mock_calls == []
    assert "delivery_failed" in stack.events()
