"""画面設計「録音の画面」を元にした結合テスト。

本物の録音の画面を offscreen で開き、UiDeps は差し替えた関数で受ける。
窓を出す・閉じる条件は、本物のトレイ・文字起こし中の表示とつないだ UiController の state_changed で確かめる。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from tests.integration.ui.helpers import Ui, button_texts, find

if TYPE_CHECKING:
    from voice_paste.shared.settings import Settings

AI_NAME_LIMIT_PX = 120
"""AI チャットの送り先の名前を省略する幅（画面設計の「名前はボタンの幅で … に省略」）。"""


def _opened(make_ui: Callable[..., Ui], settings: Settings | None = None) -> Ui:
    """録音の画面を開いた一式を返す。"""
    ui = make_ui(settings)
    ui.recording_window.open()
    return ui


def _settings(**groups: object) -> Settings:
    """グループごとの設定（recording・ui・outputs・hotkeys）を差し替えた Settings を作る。"""
    from voice_paste.shared.settings import Settings

    return Settings(**groups)


# === recording_window ===


@pytest.mark.parametrize(
    ("entry", "state", "hide_window", "shown"),
    [
        pytest.param("hotkey", "recording", False, True, id="hotkey_recording"),
        pytest.param("hotkey", "paused", False, True, id="hotkey_paused"),
        pytest.param("tray", "recording", False, True, id="tray_recording"),
        pytest.param("api", "recording", False, False, id="api_recording"),
        pytest.param("hotkey", "transcribing", False, False, id="hotkey_transcribing"),
        pytest.param("hotkey", "recording", True, False, id="hide_window"),
    ],
)
def test_recording_window_visible_when(
    make_ui: Callable[..., Ui], entry: str, state: str, hide_window: bool, shown: bool
) -> None:
    """ホットキー・トレイから始めた録音の間だけ出る。画面を出さない設定・API の録音では出さない（表示条件）。"""
    from voice_paste.shared.settings import RecordingSettings

    # 準備
    ui = make_ui(_settings(recording=RecordingSettings(hide_window=hide_window)))

    # 実行
    ui.notify_state(entry, state)

    # 検証
    assert ui.recording_window.isVisible() is shown


def test_recording_window_visible_when_idle(make_ui: Callable[..., Ui]) -> None:
    """待機中に戻ると閉じる（確定・取り消しで閉じる）。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.notify_state(None)

    # 検証
    assert not ui.recording_window.isVisible()


@pytest.mark.parametrize("topmost", [True, False], ids=["topmost_on", "topmost_off"])
def test_recording_window_does_not_take_focus(
    make_ui: Callable[..., Ui], topmost: bool
) -> None:
    """出したときにフォーカスを取らない。ui.topmost がオンなら最前面に残す指定を足す（Tool・枠なし）。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(topmost=topmost)))

    # 実行
    ui.recording_window.open()

    # 検証
    window = ui.recording_window
    flags = window.windowFlags()
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is topmost


@pytest.mark.parametrize("follow_cursor", [True, False], ids=["follow_cursor", "primary"])
def test_recording_window_position_when_top_left(
    make_ui: Callable[..., Ui], follow_cursor: bool
) -> None:
    """設定のモニターの作業領域の、設定の位置（左上は端から 24px）に出る。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(position="top-left", follow_cursor=follow_cursor)))

    # 実行
    ui.recording_window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    window = ui.recording_window
    assert window.x() == available.left() + 24
    assert window.y() == available.top() + 24


def test_recording_window_position_when_bottom_right(make_ui: Callable[..., Ui]) -> None:
    """右下の位置は、作業領域の右下から 24px 離れる。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(position="bottom-right")))

    # 実行
    ui.recording_window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    window = ui.recording_window
    assert window.x() + window.width() == available.left() + available.width() - 24
    assert window.y() + window.height() == available.top() + available.height() - 24


# === state_label ===


def test_state_label_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は、赤の点と「録音中」の文字で出す（色だけで伝えない）。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    label = find(ui.recording_window, QLabel, "state_label")
    assert "録音中" in label.text()
    assert "●" in label.text()


def test_state_label_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は「一時停止中」の文字で出す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    assert "一時停止中" in find(ui.recording_window, QLabel, "state_label").text()


# === elapsed_label ===


def test_elapsed_label_when_opened(make_ui: Callable[..., Ui]) -> None:
    """出したときに 0 から数え、1 時間未満は mm:ss の形（00:00）で出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:00"


def test_elapsed_label_when_running(make_ui: Callable[..., Ui]) -> None:
    """録音の間は経過時間が進む。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.qWait(1200)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:01"


def test_elapsed_label_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は止めた時点のまま止まり、再開すると続きから進む。"""
    # 準備
    ui = _opened(make_ui)
    QTest.qWait(1200)
    ui.recording_window.set_paused(True)
    label = find(ui.recording_window, QLabel, "elapsed_label")
    paused_text = label.text()

    # 実行
    QTest.qWait(1200)
    still_paused_text = label.text()
    ui.recording_window.set_paused(False)
    QTest.qWait(1200)

    # 検証
    assert paused_text == "00:01"
    assert still_paused_text == "00:01"
    assert label.text() == "00:02"


def test_elapsed_label_format_when_over_one_hour() -> None:
    """1 時間以上は h:mm:ss の形（1:02:37）で出す。"""
    from voice_paste.ui.windows.recording_window import format_clock

    # 実行・検証
    assert format_clock(42_000) == "00:42"
    assert format_clock(3_757_000) == "1:02:37"


# === waveform ===


def test_waveform_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は音量を取り続け（UiDeps.level）、一時停止中は取らずに最後の形のまま出す。"""
    # 準備
    ui = _opened(make_ui)
    level = ui.deps.level
    QTest.qWait(300)
    calls_while_recording = level.call_count

    # 実行
    ui.recording_window.set_paused(True)
    calls_at_pause = level.call_count
    QTest.qWait(300)

    # 検証
    assert calls_while_recording > 0
    assert level.call_count == calls_at_pause
    assert find(ui.recording_window, QWidget, "waveform").isVisible()


# === pause_button・resume_button ===


def test_pause_button_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は一時停止のボタンだけを出し、名前の横に一時停止のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    pause = find(window, QPushButton, "pause_button")
    assert pause.isVisible()
    assert button_texts(pause) == ["一時停止", "Ctrl+Alt+Z"]
    assert not find(window, QPushButton, "resume_button").isVisible()


def test_resume_button_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は、一時停止のボタンと同じ場所に再開のボタンを出し、同じホットキーを出す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    window = ui.recording_window
    resume = find(window, QPushButton, "resume_button")
    assert resume.isVisible()
    assert button_texts(resume) == ["再開", "Ctrl+Alt+Z"]
    assert not find(window, QPushButton, "pause_button").isVisible()


def test_pause_button_action(make_ui: Callable[..., Ui]) -> None:
    """一時停止のボタンは SessionManager.pause を、再開のボタンは resume を呼ぶ。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(find(ui.recording_window, QPushButton, "pause_button"), Qt.MouseButton.LeftButton)
    ui.recording_window.set_paused(True)
    QTest.mouseClick(find(ui.recording_window, QPushButton, "resume_button"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.pause.assert_called_once()
    ui.deps.resume.assert_called_once()


# === cancel_button ===


def test_cancel_button_label(make_ui: Callable[..., Ui]) -> None:
    """取り消しのボタンは常に出し、名前の横に取り消しのホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    cancel = find(ui.recording_window, QPushButton, "cancel_button")
    assert cancel.isVisible()
    assert button_texts(cancel) == ["取り消す", "Ctrl+Alt+Q"]


def test_cancel_button_action(make_ui: Callable[..., Ui]) -> None:
    """取り消しのボタンは録音を捨て（SessionManager.cancel）、窓を閉じる。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(find(ui.recording_window, QPushButton, "cancel_button"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.cancel.assert_called_once()
    assert not ui.recording_window.isVisible()


# === outputs_heading・output_button_{output_id} ===


def test_outputs_heading_when_outputs_on(make_ui: Callable[..., Ui]) -> None:
    """オンの出力先（AI チャットを除く）があれば、見出し「確定して届ける」を出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    heading = find(ui.recording_window, QLabel, "outputs_heading")
    assert heading.isVisible()
    assert heading.text() == "確定して届ける"


def test_outputs_heading_when_outputs_off(make_ui: Callable[..., Ui]) -> None:
    """AI チャットを除く出力先が全てオフなら、見出しを出さない。"""
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
    )

    # 実行
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(enabled=False),
                PasteOnlySettings(enabled=False),
                CopyOnlySettings(enabled=False),
                AiChatSettings(),
            ]
        ),
    )

    # 検証
    assert not find(ui.recording_window, QLabel, "outputs_heading").isVisible()


def test_output_buttons_when_all_on(make_ui: Callable[..., Ui]) -> None:
    """オンの出力先ごとに、設定の並びで 1 つずつ出し、名前の横にその出力先のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "output_button_paste_and_send")) == [
        "貼り付けて送信",
        "Ctrl+Alt+D",
    ]
    assert button_texts(find(window, QPushButton, "output_button_paste_only")) == [
        "貼り付けのみ",
        "Ctrl+Alt+V",
    ]
    assert button_texts(find(window, QPushButton, "output_button_copy_only")) == [
        "コピーのみ",
        "Ctrl+Alt+C",
    ]


def test_output_buttons_when_some_off(make_ui: Callable[..., Ui]) -> None:
    """オフの出力先のボタンは出さない。"""
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
    )

    # 実行
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(),
                PasteOnlySettings(enabled=False),
                CopyOnlySettings(),
                AiChatSettings(),
            ]
        ),
    )

    # 検証
    window = ui.recording_window
    assert window.findChild(QPushButton, "output_button_paste_only") is None
    assert find(window, QPushButton, "output_button_paste_and_send").isVisible()
    assert find(window, QPushButton, "output_button_copy_only").isVisible()


def test_output_buttons_primary(make_ui: Callable[..., Ui]) -> None:
    """オンのうち一番上の出力先のボタンを、主の操作にする。"""
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
    )

    # 実行（一番上の貼り付けて送信をオフにする）
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(enabled=False),
                PasteOnlySettings(),
                CopyOnlySettings(),
                AiChatSettings(),
            ]
        ),
    )

    # 検証
    window = ui.recording_window
    assert find(window, QPushButton, "output_button_paste_only").property("primary") is True
    assert find(window, QPushButton, "output_button_copy_only").property("primary") is False


@pytest.mark.parametrize("paused", [False, True], ids=["recording", "paused"])
def test_output_button_action(make_ui: Callable[..., Ui], paused: bool) -> None:
    """出力先のボタンはその出力先の ID で録音を確定し、窓を閉じる。一時停止中でも確定できる。"""
    # 準備
    ui = _opened(make_ui)
    ui.recording_window.set_paused(paused)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "output_button_paste_only"),
        Qt.MouseButton.LeftButton,
    )

    # 検証
    ui.deps.complete.assert_called_once_with("paste_only", None)
    assert not ui.recording_window.isVisible()


# === ai_chat_heading・ai_chat_button_{n} ===


def test_ai_chat_heading_when_targets_shown(make_ui: Callable[..., Ui]) -> None:
    """出力先 ai_chat がオンで出す送り先があれば、見出し「AI チャットへ送る」を出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    heading = find(ui.recording_window, QLabel, "ai_chat_heading")
    assert heading.isVisible()
    assert heading.text() == "AI チャットへ送る"


def test_ai_chat_heading_when_ai_chat_off(make_ui: Callable[..., Ui]) -> None:
    """出力先 ai_chat がオフなら、見出しも送り先のボタンも出さない。"""
    from voice_paste.shared.settings import AiChatSettings

    # 実行
    ui = _opened(make_ui, _settings(outputs=[AiChatSettings(enabled=False)]))

    # 検証
    window = ui.recording_window
    assert not find(window, QLabel, "ai_chat_heading").isVisible()
    assert window.findChild(QPushButton, "ai_chat_button_0") is None


def test_ai_chat_heading_when_all_targets_off(make_ui: Callable[..., Ui]) -> None:
    """出す送り先が 1 つも無ければ、見出しを出さない。"""
    from voice_paste.shared.settings import AiChatSettings, AiChatTarget

    # 実行
    targets = [
        AiChatTarget(name="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1", enabled=False)
    ]
    ui = _opened(make_ui, _settings(outputs=[AiChatSettings(targets=targets)]))

    # 検証
    assert not find(ui.recording_window, QLabel, "ai_chat_heading").isVisible()


def test_ai_chat_buttons_when_default(make_ui: Callable[..., Ui]) -> None:
    """出す送り先ごとに、設定の並びで 1 つずつ出し、名前の横に送り先のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "ai_chat_button_0")) == ["ChatGPT", "Ctrl+Alt+1"]
    assert button_texts(find(window, QPushButton, "ai_chat_button_1")) == ["Google AI", "Ctrl+Alt+2"]
    assert button_texts(find(window, QPushButton, "ai_chat_button_2")) == ["Claude", "Ctrl+Alt+3"]


def test_ai_chat_buttons_when_target_off(make_ui: Callable[..., Ui]) -> None:
    """出さないとした送り先のボタンは出さない（残りは詰めて 0 から数える）。"""
    from voice_paste.shared.settings import AiChatSettings, AiChatTarget

    # 実行
    targets = [
        AiChatTarget(name="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1", enabled=False),
        AiChatTarget(name="Claude", url="https://claude.ai/new", hotkey="<ctrl>+<alt>+3"),
    ]
    ui = _opened(make_ui, _settings(outputs=[AiChatSettings(targets=targets)]))

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "ai_chat_button_0")) == ["Claude", "Ctrl+Alt+3"]
    assert window.findChild(QPushButton, "ai_chat_button_1") is None


def test_ai_chat_button_when_name_is_long(make_ui: Callable[..., Ui]) -> None:
    """名前はボタンの幅で … に省略し、かざすと全体を出す。ホットキーは省略しない。"""
    from voice_paste.shared.settings import AiChatSettings, AiChatTarget

    # 実行
    long_name = "とても長い名前の AI チャットの送り先をここに書く"
    targets = [AiChatTarget(name=long_name, url="https://example.com", hotkey="<ctrl>+<alt>+1")]
    ui = _opened(make_ui, _settings(outputs=[AiChatSettings(targets=targets)]))

    # 検証
    button = find(ui.recording_window, QPushButton, "ai_chat_button_0")
    name_text, hotkey_text = button_texts(button)
    assert name_text.endswith("…")
    assert name_text != long_name
    assert hotkey_text == "Ctrl+Alt+1"
    assert button.toolTip() == long_name


@pytest.mark.parametrize("paused", [False, True], ids=["recording", "paused"])
def test_ai_chat_button_action(make_ui: Callable[..., Ui], paused: bool) -> None:
    """送り先のボタンは出力先 ai_chat と送り先の URL で録音を確定し、窓を閉じる。一時停止中でも確定できる。"""
    # 準備
    ui = _opened(make_ui)
    ui.recording_window.set_paused(paused)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "ai_chat_button_2"), Qt.MouseButton.LeftButton
    )

    # 検証
    ui.deps.complete.assert_called_once_with("ai_chat", "https://claude.ai/new")
    assert not ui.recording_window.isVisible()
