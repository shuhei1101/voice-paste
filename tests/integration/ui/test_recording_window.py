"""画面設計「録音の画面」を元にした結合テスト。

本物の録音の画面を offscreen で開き、UiDeps は差し替えた関数で受ける。
窓を出す・閉じる条件は、本物のトレイ・文字起こし中の表示とつないだ UiController の state_changed で確かめる。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from tests.integration.ui.helpers import Ui, button_texts, find, grab_head_row, no_modal

if TYPE_CHECKING:
    from voice_paste.shared.settings import Settings

PRESET_COLUMNS = 3
"""カスタムプリセットのボタンを横に並べる数（画面設計の「3 件ずつ横に並べて 4 件目から次の行へ折り返す」）。"""


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
    """オンの出力先があれば、見出し「確定して届ける」を出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    heading = find(ui.recording_window, QLabel, "outputs_heading")
    assert heading.isVisible()
    assert heading.text() == "確定して届ける"


def test_outputs_heading_when_outputs_off(make_ui: Callable[..., Ui]) -> None:
    """出力先が全てオフなら、見出しを出さない。"""
    from voice_paste.shared.settings import (
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


# === presets_heading・preset_button_{n} ===


def _presets_settings(*presets: object) -> Settings:
    """カスタムプリセットを並べた Settings を作る。"""
    return _settings(presets=list(presets))


def _browser(title: str, hotkey: str = "", *, enabled: bool = True, url: str = "https://a.example") -> object:
    """ブラウザ添付のプリセットを作る。"""
    from voice_paste.shared.settings import BrowserPreset

    return BrowserPreset(title=title, url=url, hotkey=hotkey, enabled=enabled)


def _endpoint(title: str, hotkey: str = "", *, enabled: bool = True) -> object:
    """エンドポイントへ送るのプリセットを作る。"""
    from voice_paste.shared.settings import EndpointPreset

    return EndpointPreset(
        title=title, url="http://127.0.0.1:9000/hook", hotkey=hotkey, enabled=enabled
    )


def test_presets_heading_when_presets_enabled(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットが 1 つ以上あれば、見出し「カスタムプリセット」を出す。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT")))

    # 検証
    heading = find(ui.recording_window, QLabel, "presets_heading")
    assert heading.isVisible()
    assert heading.text() == "カスタムプリセット"


def test_presets_heading_when_no_presets(make_ui: Callable[..., Ui]) -> None:
    """既定（プリセットが無い）なら、見出しもボタンも出さない。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert not find(window, QLabel, "presets_heading").isVisible()
    assert window.findChild(QPushButton, "preset_button_0") is None


def test_presets_heading_when_all_disabled(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットが 1 つも無ければ、見出しを出さない。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT", enabled=False)))

    # 検証
    assert not find(ui.recording_window, QLabel, "presets_heading").isVisible()


def test_preset_buttons_order(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットごとに 1 つずつ、ブラウザ添付の並び → エンドポイントへ送るの並びの順に出し、名前の横にホットキーを出す。"""
    # 実行（設定の並びはエンドポイントが先。ボタンはブラウザ添付が先）
    ui = _opened(
        make_ui,
        _presets_settings(
            _endpoint("受け口", "<ctrl>+<alt>+4"),
            _browser("ChatGPT", "<ctrl>+<alt>+1"),
            _browser("Claude", "<ctrl>+<alt>+3"),
        ),
    )

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "preset_button_0")) == ["ChatGPT", "Ctrl+Alt+1"]
    assert button_texts(find(window, QPushButton, "preset_button_1")) == ["Claude", "Ctrl+Alt+3"]
    assert button_texts(find(window, QPushButton, "preset_button_2")) == ["受け口", "Ctrl+Alt+4"]


def test_preset_buttons_when_disabled(make_ui: Callable[..., Ui]) -> None:
    """無効なプリセットのボタンは出さない（残りは詰めて 0 から数える）。"""
    # 実行
    ui = _opened(
        make_ui,
        _presets_settings(_browser("ChatGPT", "<ctrl>+<alt>+1", enabled=False), _browser("Claude")),
    )

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "preset_button_0")) == ["Claude"]
    assert window.findChild(QPushButton, "preset_button_1") is None


def test_preset_buttons_when_hotkey_empty(make_ui: Callable[..., Ui]) -> None:
    """ホットキーが空のプリセットは、タイトルだけを出す。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT")))

    # 検証
    assert button_texts(find(ui.recording_window, QPushButton, "preset_button_0")) == ["ChatGPT"]


def test_preset_buttons_wrap(make_ui: Callable[..., Ui]) -> None:
    """3 件ずつ横に並べ、4 件目から次の行へ折り返す（種類の境目でも行を変えない）。"""
    # 実行（ブラウザ添付 2 件 + エンドポイントへ送る 2 件）
    ui = _opened(
        make_ui,
        _presets_settings(_browser("A"), _browser("B"), _endpoint("C"), _endpoint("D")),
    )

    # 検証
    window = ui.recording_window
    positions = [
        (button.geometry().y(), button.geometry().x())
        for button in (find(window, QPushButton, f"preset_button_{n}") for n in range(4))
    ]
    first_row = {y for y, _x in positions[:PRESET_COLUMNS]}
    assert len(first_row) == 1
    assert positions[PRESET_COLUMNS][0] > positions[0][0]


def test_preset_button_when_title_is_long(make_ui: Callable[..., Ui]) -> None:
    """タイトルはボタンの幅で … に省略し、かざすと全体を出す。ホットキーは省略しない。"""
    # 実行
    long_title = "とても長い名前のプリセットのタイトルをここに書く"
    ui = _opened(make_ui, _presets_settings(_browser(long_title, "<ctrl>+<alt>+1")))

    # 検証
    button = find(ui.recording_window, QPushButton, "preset_button_0")
    title_text, hotkey_text = button_texts(button)
    assert title_text.endswith("…")
    assert title_text != long_title
    assert hotkey_text == "Ctrl+Alt+1"
    assert button.toolTip() == long_title


@pytest.mark.parametrize("paused", [False, True], ids=["recording", "paused"])
def test_preset_button_action(make_ui: Callable[..., Ui], paused: bool) -> None:
    """プリセットのボタンはそのプリセットで録音を確定し、窓を閉じる。一時停止中でも確定できる。"""
    # 準備
    claude = _browser("Claude", url="https://claude.ai/new")
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT"), claude))
    ui.recording_window.set_paused(paused)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "preset_button_1"), Qt.MouseButton.LeftButton
    )

    # 検証
    ui.deps.complete.assert_called_once_with(None, claude)
    assert not ui.recording_window.isVisible()


# === head_row ===


def test_head_row_layout(make_ui: Callable[..., Ui]) -> None:
    """見出しの行に、左端のつかむ印・状態の表示・経過時間・隠すと×のボタンを並べる。"""
    from voice_paste.ui.windows.recording_window import GripIcon

    # 実行
    ui = _opened(make_ui)

    # 検証
    row = find(ui.recording_window, QWidget, "head_row")
    assert isinstance(row.layout().itemAt(0).widget(), GripIcon)
    for name, cls in (
        ("state_label", QLabel),
        ("elapsed_label", QLabel),
        ("hide_button", QPushButton),
        ("close_button", QPushButton),
    ):
        assert row.isAncestorOf(find(ui.recording_window, cls, name))


def test_head_row_cursor(make_ui: Callable[..., Ui]) -> None:
    """行にかざすと、カーソルが移動の形になる。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    row = find(ui.recording_window, QWidget, "head_row")
    assert row.cursor().shape() == Qt.CursorShape.SizeAllCursor


@pytest.mark.parametrize(
    "label", [None, "state_label", "elapsed_label"], ids=["blank", "state", "elapsed"]
)
def test_head_row_action(
    make_ui: Callable[..., Ui], system_move: MagicMock, label: str | None
) -> None:
    """行のどこをつかんでも（状態の表示・経過時間の上を含む）、窓の移動を OS に任せる（ドラッグで窓を動かす）。"""
    # 準備
    ui = _opened(make_ui)
    row = find(ui.recording_window, QWidget, "head_row")
    grabbed = row.rect().center()
    if label is not None:
        target = find(ui.recording_window, QLabel, label)
        grabbed = target.mapTo(row, target.rect().center())

    # 実行
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=grabbed)

    # 検証
    system_move.assert_called_once_with()


def test_head_row_action_when_buttons_pressed(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """隠す・× の上はつかめない（押しても窓の移動を始めない）。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )
    ui.recording_window.open()
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "close_button"), Qt.MouseButton.LeftButton
    )

    # 検証
    system_move.assert_not_called()


def test_head_row_action_does_not_stop_recording(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """動かしている間も録音と経過時間は止めない。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    grab_head_row(ui.recording_window)
    QTest.qWait(1200)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:01"
    ui.deps.pause.assert_not_called()
    ui.deps.cancel.assert_not_called()
    assert ui.recording_window.isVisible()


def test_moved_position_when_dragged(make_ui: Callable[..., Ui], system_move: MagicMock) -> None:
    """窓を動かした回は、放した位置を返す。"""
    # 準備
    ui = _opened(make_ui)
    window = ui.recording_window
    grab_head_row(window)

    # 実行
    window.move(window.pos() + QPoint(60, 40))

    # 検証
    assert window.moved_position() == window.pos()


def test_moved_position_when_not_grabbed(make_ui: Callable[..., Ui]) -> None:
    """見出しの行をつかんでいない回は、None を返す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert ui.recording_window.moved_position() is None


def test_moved_position_when_only_pressed(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """見出しの行を押しただけで位置が変わらない回は、None を返す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    grab_head_row(ui.recording_window)

    # 検証
    assert ui.recording_window.moved_position() is None


def test_moved_position_when_shifted_after_open(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """出した後に OS が窓の位置をずらしても、つかんだだけの回は None を返す。"""
    # 準備
    ui = _opened(make_ui)
    window = ui.recording_window
    window.move(window.pos() + QPoint(8, 8))

    # 実行
    grab_head_row(window)

    # 検証
    assert window.moved_position() is None


def test_moved_position_when_reopened(make_ui: Callable[..., Ui], system_move: MagicMock) -> None:
    """動かした位置はその回だけ使い、次の録音は設定の位置に出す。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = _opened(make_ui, _settings(ui=UiSettings(position="top-left")))
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(120, 90))
    window.close_window()

    # 実行
    window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    assert window.pos() == QPoint(available.left() + 24, available.top() + 24)
    assert window.moved_position() is None


# === hide_button ===


def test_hide_button_label(make_ui: Callable[..., Ui]) -> None:
    """かざすと戻し方を添えた説明を出す。録音開始と同じホットキーの出力先がある設定（既定）では、トレイのアイコンで戻す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    hide = find(ui.recording_window, QPushButton, "hide_button")
    assert hide.toolTip() == "録音の画面を隠す（トレイのアイコンで戻す）"
    assert hide.accessibleName() == "録音の画面を隠す"


def test_hide_button_label_when_start_hotkey_is_free(make_ui: Callable[..., Ui]) -> None:
    """録音開始と同じホットキーの出力先が無い設定では、トレイのアイコンか録音開始のホットキーで戻すと添える。"""
    from voice_paste.shared.settings import HotkeySettings

    # 実行
    ui = _opened(make_ui, _settings(hotkeys=HotkeySettings(start="<ctrl>+<alt>+r")))

    # 検証
    hide = find(ui.recording_window, QPushButton, "hide_button")
    assert hide.toolTip() == "録音の画面を隠す（トレイのアイコンか Ctrl+Alt+R で戻す）"


def test_hide_button_action(make_ui: Callable[..., Ui]) -> None:
    """その回だけ録音の画面を隠す。セッションの状態・録音は止めず、確定・一時停止・取り消しを呼ばない。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )

    # 検証
    assert not ui.recording_window.isVisible()
    ui.deps.pause.assert_not_called()
    ui.deps.cancel.assert_not_called()
    ui.deps.complete.assert_not_called()


def test_hide_button_action_then_next_recording(make_ui: Callable[..., Ui]) -> None:
    """隠すのはその回だけで、次の録音ではいつもどおり出す。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )
    ui.notify_state(None)

    # 実行
    ui.notify_state("hotkey", "recording")

    # 検証
    assert ui.recording_window.isVisible()


def test_hide_button_action_when_paused_while_hidden(make_ui: Callable[..., Ui]) -> None:
    """隠している間に一時停止しても、窓は出さない。戻すと一時停止中を示し、経過時間は一時停止した時点で止まっている。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    QTest.qWait(1200)
    ui.controller.hide_recording()
    QTest.qWait(1200)

    # 実行
    ui.notify_state("hotkey", "paused")
    hidden_after_pause = not ui.recording_window.isVisible()
    QTest.qWait(1200)
    ui.controller.show_recording()

    # 検証
    window = ui.recording_window
    assert hidden_after_pause
    assert window.isVisible()
    assert "一時停止中" in find(window, QLabel, "state_label").text()
    assert find(window, QLabel, "elapsed_label").text() == "00:02"


def test_hide_button_action_then_restore(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """隠した画面を戻すと、隠す前の位置に、経過時間と状態を保ったまま出る。窓の作りはフォーカスを取らない出し方のまま。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(70, 50))
    moved_to = window.pos()
    QTest.qWait(1200)
    ui.controller.hide_recording()
    QTest.qWait(1200)

    # 実行
    ui.controller.show_recording()

    # 検証
    assert window.isVisible()
    assert window.pos() == moved_to
    assert find(window, QLabel, "elapsed_label").text() == "00:02"
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_hide_button_action_when_hide_window_setting(make_ui: Callable[..., Ui]) -> None:
    """画面を出さない設定の録音では、戻す操作をしても窓を出さない。"""
    from voice_paste.shared.settings import RecordingSettings

    # 準備
    ui = make_ui(_settings(recording=RecordingSettings(hide_window=True)))
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.controller.show_recording()

    # 検証
    assert not ui.recording_window.isVisible()


# === close_button ===


def test_close_button_label(make_ui: Callable[..., Ui]) -> None:
    """かざすと「取り消す」と取り消しのホットキーを添えた説明を出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    close = find(ui.recording_window, QPushButton, "close_button")
    assert close.toolTip() == "取り消す（Ctrl+Alt+Q）"
    assert close.accessibleName() == "取り消す"


def test_close_button_action(make_ui: Callable[..., Ui]) -> None:
    """「取り消す」のボタンと同じく録音を捨て（SessionManager.cancel）、窓を閉じる。確認は挟まない。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    with no_modal():
        QTest.mouseClick(
            find(ui.recording_window, QPushButton, "close_button"), Qt.MouseButton.LeftButton
        )

    # 検証
    ui.deps.cancel.assert_called_once()
    ui.deps.complete.assert_not_called()
    assert not ui.recording_window.isVisible()
