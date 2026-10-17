"""画面の結合テスト用の補助。

画面は offscreen の QApplication（tests/conftest.py の qapp）で開き、UiDeps は差し替えた関数（Mock）で受ける。
単体テストと同じ UiDeps・Session の組み立てを使い回す。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from tests.unit.voice_paste.ui.helpers import FakeClock, make_session, make_ui_deps

if TYPE_CHECKING:
    from voice_paste.shared.settings import Preset, Settings
    from voice_paste.ui.controller import UiController, UiDeps
    from voice_paste.ui.tray import Tray
    from voice_paste.ui.windows.recording_window import RecordingWindow
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

__all__ = ["FakeClock", "make_session", "make_ui_deps"]

WidgetT = TypeVar("WidgetT", bound=QWidget)


def find(root: QWidget, cls: type[WidgetT], name: str) -> WidgetT:
    """画面の項目 ID（objectName）の部品を引く。無ければ失敗させる。"""
    found = root.findChild(cls, name)
    assert found is not None, f"{name} の部品が無い"
    return found


def button_texts(button: QPushButton) -> list[str]:
    """ボタンの中に並んだ文字（名前・ホットキー）を、並びの順に返す。"""
    return [label.text() for label in button.findChildren(QLabel)]


def grab_head_row(window: RecordingWindow) -> None:
    """録音の画面の見出しの行（head_row）の中ほどを押して放す（窓の移動は startSystemMove に任せる）。"""
    row = find(window, QWidget, "head_row")
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    QTest.mouseRelease(row, Qt.MouseButton.LeftButton, pos=row.rect().center())


FACE_OFFSET_PX = 4
"""窓の左端から、縁と角丸の内側（面だけが描かれる位置）までの距離。"""


def edge_and_face_colors(widget: QWidget) -> tuple[QColor, QColor]:
    """窓を描いた画像の、左端の縦の中ほどの画素の色（窓の外側の縁）と、そこから内側へ進んだ画素の色（窓の面）を返す。"""
    image = widget.grab().toImage()
    middle = image.height() // 2
    return image.pixelColor(0, middle), image.pixelColor(FACE_OFFSET_PX, middle)


@dataclass
class Ui:
    """本物のトレイ・録音の画面・文字起こし中の表示を UiController へつないだ一式と、渡した UiDeps。"""

    controller: UiController
    tray: Tray
    recording_window: RecordingWindow
    indicator: TranscribingIndicator
    deps: UiDeps

    def notify_state(
        self,
        entry: str | None,
        state: str | None = None,
        *,
        output_id: str | None = None,
        output_preset: Preset | None = None,
    ) -> None:
        """今のセッションを入口・状態・確定で選んだ出力先かプリセットで差し替え、state_changed を受けさせる（None は待機中）。"""
        session = (
            None
            if entry is None
            else make_session(
                entry, state or "recording", output_id=output_id, output_preset=output_preset
            )
        )
        self.deps.current_session.return_value = session
        self.controller.on_notified("state_changed", None)

    def notify_output_changed(self, output_id: str) -> None:
        """届ける出力先を差し替えたことを知らせる（output_changed）。"""
        self.controller.on_notified("output_changed", output_id)

    def close(self) -> None:
        """出ている窓とトレイを片付ける。"""
        self.recording_window.close_window()
        self.indicator.close_window()
        self.tray.hide()


def build_ui(tmp_path: Path, settings: Settings | None = None, **deps_overrides: object) -> Ui:
    """本物のトレイ・窓を UiController へつないで返す（UiDeps の関数は Mock）。"""
    from voice_paste.ui.controller import UiController
    from voice_paste.ui.tray import Tray
    from voice_paste.ui.windows.recording_window import RecordingWindow
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    deps = make_ui_deps(tmp_path, settings=settings, **deps_overrides)
    tray = Tray(settings_dir=deps.settings_dir, log_dir=deps.log_dir)
    recording_window = RecordingWindow(deps)
    indicator = TranscribingIndicator(deps)
    controller = UiController(
        deps, tray=tray, recording_window=recording_window, indicator=indicator
    )
    return Ui(
        controller=controller,
        tray=tray,
        recording_window=recording_window,
        indicator=indicator,
        deps=deps,
    )


class ModalDriver:
    """exec で止まるモーダルのダイアログに、ボタンの項目 ID を押させる。

    answer で予約してから、ダイアログを出す操作を行い、verify で押せたかを確かめる。
    """

    def __init__(self) -> None:
        self.answered = False
        self.error: BaseException | None = None
        self.box: QMessageBox | None = None

    def answer(
        self, button_name: str, inspect: Callable[[QMessageBox], None] | None = None
    ) -> None:
        """次に出るモーダルで inspect（あれば）を呼び、button_name のボタンを押す。"""

        def _click() -> None:
            """モーダルのダイアログを引いて、見て、ボタンを押す。"""
            box = QApplication.activeModalWidget()
            try:
                assert isinstance(box, QMessageBox), "モーダルのダイアログが出ていない"
                self.box = box
                if inspect is not None:
                    inspect(box)
                find(box, QPushButton, button_name).click()
                self.answered = True
            except BaseException as error:  # noqa: BLE001 タイマーの中の失敗を verify で出し直す
                self.error = error
                if isinstance(box, QMessageBox):
                    box.reject()

        QTimer.singleShot(0, _click)

    def verify(self) -> None:
        """ダイアログの確認とボタンの押下が済んでいることを確かめる（失敗はここで出し直す）。"""
        if self.error is not None:
            raise self.error
        assert self.answered, "モーダルのダイアログが出なかった"


@contextmanager
def no_modal() -> Iterator[None]:
    """この中でモーダルのダイアログが出たら、押せないままブロックしないよう閉じて失敗させる。"""
    seen: list[QMessageBox] = []

    def _watch() -> None:
        """モーダルが出ていたら、閉じて控える。"""
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            seen.append(box)
            box.reject()

    timer = QTimer()
    timer.timeout.connect(_watch)
    timer.start(20)
    try:
        yield
    finally:
        timer.stop()
    assert not seen, "出てはいけないダイアログが出た"
