"""画面設計「文字起こし中の表示」を元にした結合テスト。

窓を出す・閉じる条件は、本物のトレイ・録音の画面とつないだ UiController の state_changed で確かめる。
経過と残りの時間は、進められる時計を渡した文字起こし中の表示で確かめる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar

from tests.integration.ui.helpers import FakeClock, Ui, find, make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator


@pytest.fixture
def clocked(qapp: QApplication, tmp_path: Path) -> Iterator[tuple[TranscribingIndicator, FakeClock]]:
    """進められる時計を渡した文字起こし中の表示を開いて返す。テストの後に閉じる。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    clock = FakeClock(0.0)
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=clock)
    indicator.open()
    yield indicator, clock
    indicator.close_window()


# === transcribing_indicator ===


@pytest.mark.parametrize(
    ("entry", "state", "hide_window", "shown"),
    [
        pytest.param("hotkey", "transcribing", False, True, id="hotkey_transcribing"),
        pytest.param("tray", "delivering", False, True, id="tray_delivering"),
        pytest.param("api", "transcribing", False, False, id="api_transcribing"),
        pytest.param("hotkey", "recording", False, False, id="hotkey_recording"),
        pytest.param("hotkey", "transcribing", True, False, id="hide_window"),
    ],
)
def test_transcribing_indicator_visible_when(
    make_ui: Callable[..., Ui], entry: str, state: str, hide_window: bool, shown: bool
) -> None:
    """ホットキー・トレイのセッションが transcribing か delivering の間だけ出る。画面を出さない設定・API の録音では出さない（表示条件）。"""
    from voice_paste.shared.settings import RecordingSettings, Settings

    # 準備
    ui = make_ui(Settings(recording=RecordingSettings(hide_window=hide_window)))

    # 実行
    ui.notify_state(entry, state)

    # 検証
    assert ui.indicator.isVisible() is shown


def test_transcribing_indicator_visible_when_idle(make_ui: Callable[..., Ui]) -> None:
    """届けた・結果が空で待機中に戻ると閉じる。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "transcribing")

    # 実行
    ui.notify_state(None)

    # 検証
    assert not ui.indicator.isVisible()


@pytest.mark.parametrize("topmost", [True, False], ids=["topmost_on", "topmost_off"])
def test_transcribing_indicator_does_not_take_focus(
    make_ui: Callable[..., Ui], topmost: bool
) -> None:
    """フォーカスを取らない（貼り付け先の入力欄からフォーカスを奪わない）。ui.topmost がオンなら最前面に残す。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(topmost=topmost)))

    # 実行
    ui.indicator.open()

    # 検証
    window = ui.indicator
    flags = window.windowFlags()
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is topmost


def test_transcribing_indicator_position(make_ui: Callable[..., Ui]) -> None:
    """録音の画面と同じ位置に出る（左上の位置なら、2 つの窓の左上が同じ）。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(position="top-left")))

    # 実行
    ui.recording_window.open()
    ui.indicator.open()

    # 検証
    assert ui.indicator.pos() == ui.recording_window.pos()


# === state_label・paste_hint ===


def test_state_label(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """文字起こし中であることを、文字（文字起こし中）で出す。"""
    indicator, _ = clocked

    # 検証
    assert find(indicator, QLabel, "state_label").text() == "文字起こし中"


def test_paste_hint(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """貼り付けたい場所にカーソルを合わせるよう案内する。"""
    indicator, _ = clocked

    # 検証
    assert find(indicator, QLabel, "paste_hint").text() == "貼り付けたい場所にカーソルを合わせてください"


# === progress_bar ===


def test_progress_bar_when_no_progress(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """最初の区間の終わりが届くまでは、進みのバーを出さない（回る印だけ）。"""
    indicator, _ = clocked

    # 検証
    assert not find(indicator, QProgressBar, "progress_bar").isVisible()


def test_progress_bar_when_progressed(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """最初の区間の終わりが届いたら、整数の %（62）で出す。"""
    indicator, _ = clocked

    # 実行
    indicator.set_progress(3.1, 5.0)

    # 検証
    bar = find(indicator, QProgressBar, "progress_bar")
    assert bar.isVisible()
    assert bar.value() == 62


def test_progress_bar_when_reopened(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """次の録音で出し直すと、進みを隠して 0 から始める。"""
    indicator, _ = clocked
    indicator.set_progress(3.1, 5.0)

    # 実行
    indicator.close_window()
    indicator.open()

    # 検証
    bar = find(indicator, QProgressBar, "progress_bar")
    assert not bar.isVisible()
    assert bar.value() == 0


# === time_label ===


def test_time_label_when_no_progress(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """残りが分かるまでは「経過 1.4 秒 残りを計っています」と出す。"""
    indicator, clock = clocked

    # 実行
    clock.now = 1.4
    indicator.set_progress(0.0, 5.0)

    # 検証
    assert find(indicator, QLabel, "time_label").text() == "経過 1.4 秒 残りを計っています"


def test_time_label_when_progressed(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """経過と残りの時間・全体の時間を「経過 3.0 秒 残り 2 秒 / 5 秒」の形で出す。"""
    indicator, clock = clocked

    # 実行
    clock.now = 3.0
    indicator.set_progress(3.1, 5.0)

    # 検証
    assert find(indicator, QLabel, "time_label").text() == "経過 3.0 秒 残り 2 秒 / 5 秒"


def test_time_label_when_over_one_minute(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """1 分以上は「3 分 06 秒」の形で出す。"""
    indicator, clock = clocked

    # 実行（経過 186 秒、進み 1/2、全体 372 秒）
    clock.now = 186.0
    indicator.set_progress(186.0, 372.0)

    # 検証
    assert (
        find(indicator, QLabel, "time_label").text() == "経過 3 分 06 秒 残り 3 分 06 秒 / 6 分 12 秒"
    )
