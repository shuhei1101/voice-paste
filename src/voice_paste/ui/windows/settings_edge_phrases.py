"""設定画面の「ハルシネーション」のまとまりに置く、文頭・文末から消す文言の一覧。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.settings import EdgePhraseSettings
from voice_paste.ui.windows.settings_fields import set_invalid

HEADING_TEXT: str = "ハルシネーション"
"""まとまりの見出し。"""

INTRO_TEXT: str = "文字起こしが文頭・文末に足す、話していない文言を消す。"
"""まとまりの見出しの下に出す、一覧の文言が何を消すかの説明。"""

EMPTY_TEXT: str = "消す文言はまだありません。無い間は、文頭・文末から何も消しません。"
"""行が 1 つも無いときの文。"""

LEGEND_TEXT: str = (
    "上の行から順に当てる。* は任意の文字列に一致する。行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。"
)
"""行の順・`*` の一致・行の動かし方を示す凡例。"""

LIST_ACCESSIBLE_NAME: str = "文頭・文末から消す文言（上の行から順に当てる）"
"""文言の一覧の読み上げの名前。"""

GRIP_TEXT: str = "⠿"
"""行の左端のつまみに出す印。"""

GRIP_TOOLTIP: str = "掴んで動かす"
"""行の左端のつまみに重ねたときのツールチップ。"""

TEXT_PLACEHOLDER: str = "例: ご視聴ありがとうございました"
"""文言の欄のプレースホルダ。"""

POSITION_LABELS: tuple[tuple[str, str], ...] = (("start", "文頭"), ("end", "文末"), ("both", "両方"))
"""位置の選択の（値, 表示）。選択肢の並びもこの順。"""

DEFAULT_POSITION: str = "end"
"""足した行の位置。"""

NARROW_WIDTH_PX: int = 420
"""この幅より狭い部品では、1 行を 2 段（上に文言の欄、下に位置と消すボタン）に組み、列の見出しの行を隠す。"""

TEXT_HEADING: str = "文言"
POSITION_HEADING: str = "位置"
"""行の上に出す列の見出し（つまみと消すボタンの列は見出しを出さない）。"""

LOCATION_TEXT_LENGTH: int = 2
"""失敗の場所（添字, "text"）の長さ。"""


@dataclass(eq=False)
class _PhraseRow:
    """文言 1 行の部品と、欄の下のエラーの文。"""

    container: QFrame
    grip: QLabel
    text_edit: QLineEdit
    position_box: QComboBox
    remove_button: QPushButton
    error_label: QLabel


class _PhraseEdit(QLineEdit):
    """Alt+↑ / Alt+↓ で行を動かす依頼を出す文言の欄。"""

    move_requested = Signal(int)
    """行を動かす依頼（-1 は上へ、1 は下へ）。"""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt の名前
        """Alt+↑ / Alt+↓ なら行を動かす依頼を出し、それ以外は欄の入力として扱う。"""
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Up:
                self.move_requested.emit(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down:
                self.move_requested.emit(1)
                event.accept()
                return
        super().keyPressEvent(event)


class RowGrip(QLabel):
    """掴んで上下へ動かし、離した位置を知らせる行の左端のつまみ。"""

    released = Signal(int)
    """つまみを離した画面上の縦の位置。"""

    def __init__(self) -> None:
        """つまみの印とツールチップを出す。フォーカスは受けない。"""
        super().__init__(GRIP_TEXT)
        self.setToolTip(GRIP_TOOLTIP)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 Qt の名前
        """左ボタンで掴む（離すまでマウスを受け続ける）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 Qt の名前
        """左ボタンを離したら、離した縦の位置を知らせる。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(int(event.globalPosition().y()))
            event.accept()


class EdgePhrasePanel(QWidget):
    """設定画面の「ハルシネーション」のまとまりに置く、説明・文言の一覧・空の文・「行を足す」・凡例。

    足す・消す・並べ替え・入力はこの部品の中だけを変え、settings.toml へは設定画面の保存で書く。
    """

    changed = Signal()
    """足す・消す・並べ替え・欄の入力で値が変わった（設定画面が変えた欄の数えに使う）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """空の一覧で部品を作る。"""
        super().__init__(parent)
        self._rows: list[_PhraseRow] = []
        # 行を追う番号: 一覧の並びと同じ順に持つ。開いたとき・保存したときの分は 0 から振り、足した分はそれより大きい番号にする
        self._ids: list[int] = []
        self._baseline_count = 0
        self._next_id = 0
        self._narrow = False
        self.setObjectName("edge_phrase_panel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(HEADING_TEXT)
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        intro = QLabel(INTRO_TEXT)
        intro.setObjectName("edge_phrase_intro")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self._empty_label = QLabel(EMPTY_TEXT)
        self._empty_label.setObjectName("edge_phrase_empty")
        self._empty_label.setWordWrap(True)
        outer.addWidget(self._empty_label)

        self._header = self._build_header()
        outer.addWidget(self._header)

        self._list = QWidget()
        self._list.setObjectName("edge_phrase_list")
        self._list.setAccessibleName(LIST_ACCESSIBLE_NAME)
        self._rows_layout = QVBoxLayout(self._list)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        outer.addWidget(self._list)

        add_button = QPushButton("行を足す")
        add_button.setObjectName("add_edge_phrase_button")
        add_button.clicked.connect(self.add_phrase)
        legend = QLabel(LEGEND_TEXT)
        legend.setObjectName("edge_phrase_legend")
        legend.setProperty("role", "muted")
        legend.setWordWrap(True)
        outer.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(legend)

    # --- 値の出し入れ ---

    def set_phrases(self, phrases: Sequence[EdgePhraseSettings]) -> None:
        """渡した行で一覧を作り直す。空なら空の文を出す。"""
        self._rebuild([phrase.model_dump() for phrase in phrases], self._number_saved(len(phrases)))

    def collect(self) -> list[dict[str, Any]]:
        """今の並びの行を settings.toml と同じ形の dict（text・position）の並びにする。空の文言の行もそのまま入れる。"""
        return [
            {"text": row.text_edit.text(), "position": str(row.position_box.currentData())}
            for row in self._rows
        ]

    def add_phrase(self) -> None:
        """末尾に文言が空で位置が文末の行を足し、文言の欄へフォーカスを移して changed を emit する。"""
        values = self.collect()
        values.append({"text": "", "position": DEFAULT_POSITION})
        # 足した行には、振ったどの番号より大きい番号を振る
        added_id = self._next_id
        self._next_id += 1
        self._rebuild(values, [*self._ids, added_id])
        self._rows[-1].text_edit.setFocus()
        self.changed.emit()

    def move_phrase(self, position: int, delta: Literal[-1, 1]) -> None:
        """行を 1 つ上へか下へ動かし、動かした行の文言の欄へフォーカスを移して読み上げに伝え、changed を emit する。先頭を上へ・末尾を下へは何もしない。"""
        target = position + delta
        # 動かす先が無ければ何もしない
        if not 0 <= target < len(self._rows):
            return
        self._move_to(position, target)

    def change_values(self) -> dict[str, object]:
        """変えた欄の数えに使う値を、行 1 つ = 1 キーと、並べ替えの 1 キーで返す。"""
        values: dict[str, object] = {
            f"edge_phrases[{row_id}]": (value["text"], value["position"])
            for row_id, value in zip(self._ids, self.collect(), strict=True)
        }
        # 開いたとき・保存したときからあって今も残っている行だけで、番号の小さい順に並んでいるか（足した行は見ない）
        kept = [row_id for row_id in self._ids if row_id < self._baseline_count]
        values["edge_phrases.order"] = kept == sorted(kept)
        return values

    def mark_saved(self) -> None:
        """行の番号を、今の並びの順に 0 から振り直す（足した行も保存した行として扱う）。保存が書けた後に呼ぶ。"""
        self._ids = self._number_saved(len(self._rows))

    def focus_field(self, location: tuple[int | str, ...]) -> None:
        """失敗の場所（edge_phrases より後ろ。例 (1, "text")）で文言の欄を探し、フォーカスを移す。"""
        row = self._row_at(location)
        if row is not None:
            row.text_edit.setFocus()

    # --- エラーの表示 ---

    def show_error(self, location: tuple[int | str, ...], message: str) -> None:
        """失敗の場所の文言の欄の下にエラーを出し、欄を赤くする（同じ欄の失敗は重ねて出す）。"""
        row = self._row_at(location)
        if row is None:
            return
        label = row.error_label
        label.setText(f"{label.text()}\n{message}" if label.text() else message)
        label.show()
        set_invalid(row.text_edit, invalid=True)

    def clear_errors(self) -> None:
        """前の保存で出したエラーを全て消す。"""
        for row in self._rows:
            row.error_label.clear()
            row.error_label.hide()
            set_invalid(row.text_edit, invalid=False)

    def _row_at(self, location: tuple[int | str, ...]) -> _PhraseRow | None:
        """失敗の場所（何行目か, "text"）の行を返す。無ければ None。"""
        if len(location) != LOCATION_TEXT_LENGTH or location[1] != "text":
            return None
        position = location[0]
        if not isinstance(position, int) or not 0 <= position < len(self._rows):
            return None
        return self._rows[position]

    # --- 組み立て ---

    def _number_saved(self, count: int) -> list[int]:
        """保存した件数の行に 0 から番号を振り直し（足す番号はその次から）、その番号の並びを返す。"""
        self._baseline_count = count
        self._next_id = count
        return list(range(count))

    def _rebuild(self, values: list[dict[str, Any]], ids: list[int]) -> None:
        """行の値の並びと番号の並びで、一覧を全て作り直す。"""
        self._ids = ids
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        for position, value in enumerate(values):
            self._add_row(position, value)
        self._empty_label.setVisible(not values)
        self._list.setVisible(bool(values))
        self._sync_header()

    def _move_to(self, position: int, target: int) -> None:
        """行を target の位置へ動かし、動かした行の文言の欄へフォーカスを移して読み上げに伝える。"""
        # 動かしていなければ何もしない
        if position == target:
            return
        values = self.collect()
        ids = list(self._ids)
        values.insert(target, values.pop(position))
        ids.insert(target, ids.pop(position))
        self._rebuild(values, ids)
        moved_edit = self._rows[target].text_edit
        moved_edit.setFocus()
        QAccessible.updateAccessibility(
            QAccessibleAnnouncementEvent(moved_edit, f"{target + 1} 行目へ動かしました")
        )
        self.changed.emit()

    def _remove(self, position: int) -> None:
        """行を一覧から消す。"""
        values = self.collect()
        del values[position]
        ids = list(self._ids)
        del ids[position]
        self._rebuild(values, ids)
        self.changed.emit()

    def _drop(self, position: int, global_y: int) -> None:
        """つまみを離した縦の位置から、行の移し先（他の行のうち、中心がそれより上にある数）を決めて動かす。"""
        target = sum(
            1
            for index, row in enumerate(self._rows)
            if index != position
            and row.container.mapToGlobal(row.container.rect().center()).y() < global_y
        )
        self._move_to(position, target)

    @staticmethod
    def _build_header() -> QWidget:
        """列の見出しの行（文言・位置）を作る。つまみと消すボタンの列は、行の部品と同じ幅の空きにして欄の左端をそろえる。"""
        header = QWidget()
        header.setObjectName("edge_phrase_header")
        grid = QGridLayout(header)
        probe = QFrame()
        # 行の枠と同じ余白にして、行の欄と見出しの左端をそろえる
        margins = QGridLayout(probe).contentsMargins()
        grid.setContentsMargins(margins)
        grip_gap = QWidget()
        grip_gap.setFixedWidth(RowGrip().sizeHint().width())
        text_label = QLabel(TEXT_HEADING)
        text_label.setObjectName("edge_phrase_header_text")
        position_label = QLabel(POSITION_HEADING)
        position_label.setObjectName("edge_phrase_header_position")
        position_box = QComboBox()
        for key, label in POSITION_LABELS:
            position_box.addItem(label, key)
        position_label.setFixedWidth(position_box.sizeHint().width())
        remove_gap = QWidget()
        remove_gap.setFixedWidth(QPushButton("×").sizeHint().width())
        for label in (text_label, position_label):
            label.setProperty("role", "heading")
        grid.addWidget(grip_gap, 0, 0)
        grid.addWidget(text_label, 0, 1)
        grid.addWidget(position_label, 0, 2)
        grid.addWidget(remove_gap, 0, 3)
        grid.setColumnStretch(1, 1)
        return header

    def _sync_header(self) -> None:
        """列の見出しの行を、行があって 1 段の組みのときだけ出す（2 段の組みでは各欄の読み上げの名前に任せる）。"""
        self._header.setVisible(bool(self._rows) and not self._narrow)

    def _add_row(self, position: int, value: dict[str, Any]) -> None:
        """行 1 つ（左端のつまみ・文言の欄・位置の選択・消すボタンと、欄の下のエラーの文）を足す。"""
        frame = QFrame()
        frame.setProperty("role", "surface")
        grid = QGridLayout(frame)

        grip = RowGrip()
        grip.setObjectName(f"edge_phrase_grip_{position}")
        text_edit = _PhraseEdit(str(value["text"]))
        text_edit.setObjectName(f"edge_phrase_text_{position}")
        text_edit.setPlaceholderText(TEXT_PLACEHOLDER)
        text_edit.setAccessibleName(f"{position + 1} 行目の文言")
        position_box = QComboBox()
        position_box.setObjectName(f"edge_phrase_position_{position}")
        position_box.setAccessibleName(f"{position + 1} 行目の位置")
        for key, label in POSITION_LABELS:
            position_box.addItem(label, key)
        position_box.setCurrentIndex(max(position_box.findData(str(value["position"])), 0))
        remove_button = QPushButton("×")
        remove_button.setObjectName(f"edge_phrase_remove_{position}")
        remove_button.setAccessibleName(f"{position + 1} 行目を消す")
        error_label = QLabel()
        error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()

        text_edit.textChanged.connect(lambda _text: self.changed.emit())
        position_box.currentIndexChanged.connect(lambda _index: self.changed.emit())
        text_edit.move_requested.connect(lambda delta: self.move_phrase(position, delta))
        grip.released.connect(lambda global_y: self._drop(position, global_y))
        remove_button.clicked.connect(lambda: self._remove(position))

        row = _PhraseRow(frame, grip, text_edit, position_box, remove_button, error_label)
        self._rows.append(row)
        self._rows_layout.addWidget(frame)
        self._arrange(row)
        # 表示中の部品に足した部品は次のイベントの処理まで出ないため、すぐ出す
        frame.show()

    def _arrange(self, row: _PhraseRow) -> None:
        """行の部品を、今の幅に合わせて格子に並べる（狭ければ上の段に文言の欄、下の段に位置と消すボタン）。"""
        grid = row.container.layout()
        if not isinstance(grid, QGridLayout):
            return
        for widget in (row.grip, row.text_edit, row.position_box, row.remove_button, row.error_label):
            grid.removeWidget(widget)
        if self._narrow:
            grid.addWidget(row.grip, 0, 0, 2, 1)
            grid.addWidget(row.text_edit, 0, 1, 1, 2)
            grid.addWidget(row.position_box, 1, 1)
            grid.addWidget(row.remove_button, 1, 2)
            grid.addWidget(row.error_label, 2, 1, 1, 2)
        else:
            grid.addWidget(row.grip, 0, 0)
            grid.addWidget(row.text_edit, 0, 1)
            grid.addWidget(row.position_box, 0, 2)
            grid.addWidget(row.remove_button, 0, 3)
            grid.addWidget(row.error_label, 1, 1, 1, 3)
        grid.setColumnStretch(1, 1)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 Qt の名前
        """幅が狭ければ 1 行を 2 段に組み、広がれば 1 段に戻す。"""
        super().resizeEvent(event)
        narrow = event.size().width() < NARROW_WIDTH_PX
        if narrow != self._narrow:
            self._narrow = narrow
            for row in self._rows:
                self._arrange(row)
            self._sync_header()
