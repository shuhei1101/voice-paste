"""文字起こし中の表示（確定から届けるまで、フォーカスを取らずに出す小さな窓）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPaintEvent, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from voice_paste.shared.settings import Settings
from voice_paste.ui.placement import move_to_configured_position
from voice_paste.ui.style import load_tokens, theme_color
from voice_paste.ui.windows.window_parts import GripIcon, HeadRow, HotkeyButton, clear_layout

if TYPE_CHECKING:
    from voice_paste.ui.controller import UiDeps

TICK_MSEC: int = 100
"""経過と残りの時間を描き直す間隔（ミリ秒）。"""

SPINNER_FRAME_MSEC: int = 16
"""回るマーカーを描き直す間隔（ミリ秒）。"""

SPINNER_SIZE_PX: int = 18
"""回るマーカーの大きさ。"""

SPINNER_ARC_DEGREES: int = 100
"""回るマーカーの弧の長さ（度）。"""

FULL_CIRCLE_DEGREES: int = 360
"""円 1 周の角度。"""

SECONDS_PER_MINUTE: int = 60
"""1 分の秒数。"""

PERCENT: int = 100
"""進みの最大（%）。"""

STATE_TEXT: str = "文字起こし中"
"""状態の表示の文言。"""

HINT_TEXT: str = "貼り付けたい場所にカーソルを合わせてください"
"""貼り付けの案内の文言（貼り付けて送信・貼り付けのみ）。"""

COPY_HINT_TEXT: str = "起こした文字をクリップボードにコピーします"
"""コピーのみの案内の文言。"""

COPY_ONLY_ID: str = "copy_only"
"""コピーのみの出力先の ID。"""

OUTPUT_HEADING_TEXT: str = "出力先"
"""出力先の見出しの文言。"""

SWITCH_WINDOW_WIDTH_PX: int = 380
"""出力先の切り替えのボタンを出す回の、窓の最小の幅（ボタンが名前を省かずに収まる幅）。"""

CHECK_BADGE_SIZE_PX: int = 16
"""今の出力先のボタンの右上の角に置く、丸いマーカーの直径。"""

CHECK_BADGE_PEN_PX: float = 1.6
"""丸いマーカーの中のチェックの線の太さ。"""

CHECK_POINTS: tuple[tuple[float, float], ...] = ((4.5, 8.5), (7.0, 11.0), (11.5, 5.5))
"""丸いマーカーの中のチェックの折れ線の 3 点（直径 16 の円の左上を原点とした座標）。"""


def hint_text(output_id: str | None) -> str:
    """貼り付けの案内の文言を返す。コピーのみはコピーすることを、それ以外は貼り付ける場所の案内を返す。"""
    return COPY_HINT_TEXT if output_id == COPY_ONLY_ID else HINT_TEXT


def format_elapsed(seconds: float) -> str:
    """経過の時間を、1 分未満は小数 1 桁の秒（3.2 秒）、1 分以上は分と秒（3 分 06 秒）にする。"""
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.1f} 秒"
    return format_whole(seconds)


def format_whole(seconds: float) -> str:
    """残り・全体の時間を、1 分未満は整数の秒（2 秒）、1 分以上は分と秒（3 分 06 秒）にする。"""
    whole = round(seconds)
    if whole < SECONDS_PER_MINUTE:
        return f"{whole} 秒"
    minutes, rest = divmod(whole, SECONDS_PER_MINUTE)
    return f"{minutes} 分 {rest:02d} 秒"


class Spinner(QWidget):
    """文字起こし中であることを示す、回るマーカー。"""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(SPINNER_SIZE_PX, SPINNER_SIZE_PX)
        self._angle = 0
        spinner_msec = load_tokens()["motion"]["spinner_ms"]
        self._step = round(FULL_CIRCLE_DEGREES * SPINNER_FRAME_MSEC / spinner_msec)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        """回し始める。"""
        self._timer.start(SPINNER_FRAME_MSEC)

    def stop(self) -> None:
        """回すのを止める。"""
        self._timer.stop()

    def _advance(self) -> None:
        """弧の位置を進めて描き直す。"""
        self._angle = (self._angle + self._step) % FULL_CIRCLE_DEGREES
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 Qt の名前
        """弧を 1 本描く。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme_color("busy"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        margin = 2
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawArc(rect, -self._angle * 16, -SPINNER_ARC_DEGREES * 16)


class SwitchButton(HotkeyButton):
    """出力先の切り替えのボタン。今の出力先のボタンは選んだ状態（checked）にして、枠の右上の角から外へはみ出す丸いマーカー（チェック）を描く。

    Qt のボタンは自分の矩形の中にしか描けないため、マーカーがはみ出す分を矩形の右と上の余白に取り、地と枠はその余白の内側に描く。
    名前とホットキーは枠の中央に置き、マーカーは文字の範囲に重ねない。
    """

    def __init__(self, name: str, text: str, hotkey: str) -> None:
        super().__init__(name, text, hotkey)
        self.setCheckable(True)
        # 押してもフォーカスを取らない（貼り付け先の入力欄のフォーカスを動かさない）
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 地と枠は、スタイルシートの margin で右と上の余白の内側に描かせる
        self.setProperty("overhang", True)
        # 名前とホットキーも余白の分だけ内側に寄せ、枠の中央に置く
        overhang: int = load_tokens()["shape"]["badge_overhang"]
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(
            margins.left(), margins.top() + overhang, margins.right() + overhang, margins.bottom()
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 Qt の名前
        """面と枠を描いた後、選んだ状態なら矩形の右上の角（枠の右上の角から外へはみ出した余白）に丸いマーカーを描く。"""
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = self.width() - CHECK_BADGE_SIZE_PX
        badge = QRectF(left, 0, CHECK_BADGE_SIZE_PX, CHECK_BADGE_SIZE_PX)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme_color("accent_fg"))
        painter.drawEllipse(badge)
        # マーカーの中のチェック（色だけで伝えない）
        pen = QPen(theme_color("surface"), CHECK_BADGE_PEN_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(left + x, y) for x, y in CHECK_POINTS])


class TranscribingIndicator(QWidget):
    """確定から届けるまで、経過と残りの時間・進みと今の出力先をフォーカスを取らずに出し、固定の出力先への切り替えを受ける。

    残りの時間は、進み（区間の終わり ÷ 録音の長さ）と経過から「経過 ÷ 進み − 経過」で見積もる。
    エンジンが進みを知らせない（UiDeps.reports_progress が False）ときは、進みのバーを出さず、経過だけを出す。
    切り替えのボタンは、設定でオンの固定の出力先ごとに open で組み直す。差し替えるのは UiController で、マーカーは set_output で替える。
    """

    output_selected = Signal(str)
    """今の出力先でない切り替えのボタンが押された（押したボタンの出力先の ID）。"""

    def __init__(self, deps: UiDeps, *, clock: Callable[[], float] = time.monotonic) -> None:
        """設定の位置・ボタンを引くための依存と、経過を数える時計（秒を返す関数）を受ける。"""
        super().__init__()
        self._deps = deps
        self._clock = clock
        self._started_at = 0.0
        self._ratio: float | None = None
        self._duration_sec = 0.0
        self._output_id: str | None = None
        self._switch_buttons: dict[str, SwitchButton] = {}
        self.setObjectName("transcribing_indicator")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_time)

    def _build(self) -> None:
        """状態・進みのバー・経過と残りの時間・出力先の見出しと切り替えの並び・貼り付けの案内を並べる（切り替えのボタンは open が組み直す）。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setProperty("role", "window")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)

        # 見出しの行: つかむマーカー・回るマーカー・状態（行のどこをつかんでも窓を動かせる）
        head_row = HeadRow()
        header = QHBoxLayout(head_row)
        header.setContentsMargins(4, 4, 4, 4)
        header.addWidget(GripIcon())
        self._spinner = Spinner()
        header.addWidget(self._spinner)
        state_label = QLabel(STATE_TEXT)
        state_label.setObjectName("state_label")
        state_label.setProperty("role", "busy")
        state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(state_label)
        header.addStretch(1)
        layout.addWidget(head_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("progress_bar")
        self._progress_bar.setRange(0, PERCENT)
        self._progress_bar.setTextVisible(False)
        # 最初の区間の終わりが届くまでは、回るマーカーだけを出す
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        self._time_label = QLabel()
        self._time_label.setObjectName("time_label")
        self._time_label.setProperty("role", "mono")
        layout.addWidget(self._time_label)

        # 出力先: 区切りの線の下に、見出しと切り替えのボタンの並び（カスタムプリセットで確定した回は名前だけ）を置く
        divider = QFrame()
        divider.setProperty("role", "divider")
        layout.addWidget(divider)
        heading = QLabel(OUTPUT_HEADING_TEXT)
        heading.setObjectName("output_heading")
        heading.setProperty("role", "muted")
        layout.addWidget(heading)
        self._switch_layout = QHBoxLayout()
        layout.addLayout(self._switch_layout)
        self._preset_label = QLabel()
        self._preset_label.setObjectName("preset_label")
        layout.addWidget(self._preset_label)

        self._paste_hint = QLabel(HINT_TEXT)
        self._paste_hint.setObjectName("paste_hint")
        self._paste_hint.setProperty("role", "muted")
        layout.addWidget(self._paste_hint)

    def _rebuild_outputs(self, settings: Settings, preset_title: str | None) -> None:
        """カスタムプリセットで確定した回はその名前だけを、固定の出力先で確定した回は設定でオンの出力先の切り替えのボタンと貼り付けの案内を、設定の並びで組み直す。"""
        clear_layout(self._switch_layout)
        self._switch_buttons = {}
        self._preset_label.setVisible(preset_title is not None)
        # カスタムプリセット: 名前だけを出し、切り替えのボタンと貼り付けの案内は出さない
        if preset_title is not None:
            self._preset_label.setText(preset_title)
            self._paste_hint.hide()
            self.setMinimumWidth(0)
            return

        # 固定の出力先: オンのものを設定の並びで、ホットキーを出さない設定なら名前だけで並べる
        for output in settings.outputs:
            if not output.enabled:
                continue
            hotkey = output.hotkey if settings.ui.transcribing_show_hotkeys else ""
            button = SwitchButton(
                f"switch_button_{output.id}", self._deps.output_titles[output.id], hotkey
            )
            button.clicked.connect(
                lambda _checked=False, output_id=output.id: self._on_switch_clicked(output_id)
            )
            self._switch_layout.addWidget(button)
            self._switch_buttons[output.id] = button
        # 余りの幅は行の右の stretch に残し、ボタンの幅は名前の最も長いボタンが収まる幅から始める（前の回の窓の幅を引き継がない）
        self._switch_layout.addStretch(1)
        self._set_switch_button_width(self._widest_switch_hint())
        # 窓の最小の幅は、その幅のボタンの行が収まる幅と SWITCH_WINDOW_WIDTH_PX の大きい方（最小の幅を明示すると、レイアウトの求める最小の幅は反映されない）
        self.layout().activate()
        self.setMinimumWidth(
            max(SWITCH_WINDOW_WIDTH_PX, self.minimumSizeHint().width())
            if self._switch_buttons
            else 0
        )
        self._mark_current()
        self._paste_hint.setText(hint_text(self._output_id))
        self._paste_hint.show()

    def _widest_switch_hint(self) -> int:
        """切り替えのボタンの sizeHint の幅のうち最も大きい値を返す（ボタンが無ければ 0）。"""
        return max((button.sizeHint().width() for button in self._switch_buttons.values()), default=0)

    def _set_switch_button_width(self, width: int) -> None:
        """切り替えのボタンを全て同じ固定の幅にする。"""
        for button in self._switch_buttons.values():
            button.setFixedWidth(width)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 Qt の名前
        """窓の幅が変わるたびに、切り替えのボタンの固定の幅を行の幅から取り直す。"""
        super().resizeEvent(event)
        self._fit_switch_buttons()

    def event(self, event: QEvent) -> bool:
        """レイアウトが組み直されて行の幅が決まったときにも、切り替えのボタンの固定の幅を取り直す。

        最初に表示を出した回は、resizeEvent の時点でレイアウトがまだ行に幅を割り当てておらず、窓の幅もその後変わらないことがある。
        """
        handled = super().event(event)
        # レイアウトの組み直しはイベントを渡す前に済んでいるため、この時点の行の幅は割り当て済み
        if event.type() == QEvent.Type.LayoutRequest:
            self._fit_switch_buttons()
        return handled

    def _fit_switch_buttons(self) -> None:
        """切り替えのボタンの固定の幅を、行の幅を等分した幅と名前の最も長いボタンの幅の大きい方に取り直す。"""
        # 切り替えのボタンが無い（カスタムプリセットで確定した回）: 取り直す幅がない
        if not self._switch_buttons:
            return
        # 行の幅は、テーマの枠の線と余白を除いて、レイアウトが切り替えのボタンの行に割り当てた幅
        row_width = self._switch_layout.geometry().width()
        count = len(self._switch_buttons)
        gaps = self._switch_layout.spacing() * (count - 1)
        # 行を等分した幅（切り捨て）と名前の最も長いボタンの幅の大きい方にし、割り切れない数 px だけを行の右の stretch に残す
        share = (row_width - gaps) // count
        self._set_switch_button_width(max(share, self._widest_switch_hint()))

    def _mark_current(self) -> None:
        """今の出力先のボタンだけを選んだ状態にする。"""
        for output_id, button in self._switch_buttons.items():
            button.setChecked(output_id == self._output_id)

    def _on_switch_clicked(self, output_id: str) -> None:
        """切り替えのボタンが押された。今の出力先でなければ output_selected を emit する（マーカーは差し替えが通って set_output を受けたときに替えるため、押しただけでは動かさない）。"""
        self._mark_current()
        if output_id != self._output_id:
            self.output_selected.emit(output_id)

    def open(
        self,
        *,
        at: QPoint | None = None,
        output_id: str | None = None,
        preset_title: str | None = None,
    ) -> None:
        """経過を 0 にして進みを隠し、出力先の並び（かプリセットの名前）と貼り付けの案内を組み直し、at の座標（録音の画面の最後の位置）か、渡されなければ設定の位置に出す。"""
        settings = self._deps.get_settings()
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        if settings.ui.topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self._output_id = output_id
        self._rebuild_outputs(settings, preset_title)
        self._started_at = self._clock()
        self._ratio = None
        self._progress_bar.setValue(0)
        self._progress_bar.hide()
        self._refresh_time()

        # 座標を渡された: その位置へ／渡されなかった: 設定の位置へ
        if at is not None:
            self.adjustSize()
            self.move(at)
        else:
            move_to_configured_position(self, settings.ui)
        self.show()
        self._spinner.start()
        self._timer.start(TICK_MSEC)

    def set_progress(self, position_sec: float, duration_sec: float) -> None:
        """進みのバーと残りの時間を書き換える。"""
        if duration_sec <= 0:
            return
        self._ratio = min(position_sec / duration_sec, 1.0)
        self._duration_sec = duration_sec
        self._progress_bar.setValue(round(self._ratio * PERCENT))
        self._progress_bar.show()
        self._refresh_time()

    def set_output(self, output_id: str) -> None:
        """切り替えのボタンのマーカーと貼り付けの案内を、切り替えた先の出力先に替える。"""
        self._output_id = output_id
        self._mark_current()
        self._paste_hint.setText(hint_text(output_id))

    def close_window(self) -> None:
        """タイマーと回るマーカーを止めて窓を隠す。"""
        self._timer.stop()
        self._spinner.stop()
        self.hide()

    def _refresh_time(self) -> None:
        """経過と、見積もった残りの時間・全体の時間の文字を書き換える。"""
        elapsed = self._clock() - self._started_at
        # エンジンが進みを知らせるか
        if not self._deps.reports_progress:
            # 知らせない（OpenAI API）: 進みが届かないため、残りを見積もらず経過だけを出す
            self._time_label.setText(f"経過 {format_elapsed(elapsed)}")
            return
        # 最初の区間の終わりが届くまでは、残りを計っている
        if self._ratio is None or self._ratio <= 0:
            self._time_label.setText(f"経過 {format_elapsed(elapsed)} 残りを計っています")
            return
        remaining = max(elapsed / self._ratio - elapsed, 0.0)
        self._time_label.setText(
            f"経過 {format_elapsed(elapsed)} 残り {format_whole(remaining)}"
            f" / {format_whole(self._duration_sec)}"
        )
