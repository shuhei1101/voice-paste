"""設定画面（トレイの「設定…」から開く）と、設定画面のホットキーの欄・確認ダイアログ・欄のエラーの文言。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from PySide6.QtCore import QEvent, QKeyCombination, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from voice_paste.shared.errors import HotkeyError
from voice_paste.shared.settings import (
    HOTKEY_OVERLAP_ERROR_TYPE,
    OUTPUTS_FIELD_NAME,
    RELOAD_IMMEDIATE,
    RELOAD_RESTART,
    AiChatSettings,
    AiChatTarget,
    CopyOnlySettings,
    PasteAndSendSettings,
    PasteOnlySettings,
    Settings,
    format_error_location,
)
from voice_paste.ui.windows.settings_fields import (
    SLIDER_MAX,
    WHISPER_MODEL_CHOICES,
    Field,
    connect_changed,
    key_tokens,
    make_check_box,
    make_combo,
    make_line_edit,
    make_plain_text,
    make_radio_group,
    make_slider,
    plain_text_lines,
    reload_of,
    selected_radio,
    set_nested,
    value_at,
)

if TYPE_CHECKING:
    from voice_paste.ui.controller import UiDeps

logger = logging.getLogger(__name__)

WINDOW_TITLE: str = "voice-paste の設定"
"""設定画面と確認ダイアログの窓の題。"""

MIN_WIDTH_PX: int = 720
"""設定画面の最小の幅（欄の名前と設定のキーが語の途中で折り返さない幅）。"""

GROUP_NAMES: tuple[str, ...] = (
    "出力先",
    "ホットキー",
    "録音",
    "文字起こし",
    "画面",
    "履歴とログ",
    "API",
)
"""まとまりのメニューの並び（既定は先頭）。"""

FIELD_LAYOUT: dict[str, tuple[str, ...]] = {
    "出力先": (OUTPUTS_FIELD_NAME,),
    "ホットキー": ("hotkeys.start", "hotkeys.pause", "hotkeys.cancel", "keyboard.paste_key"),
    "録音": (
        "recording.lower_volume",
        "recording.hide_window",
        "recording.volume_percent",
        "recording.fade_sec",
    ),
    "文字起こし": (
        "transcription.engine",
        "transcription.local_whisper.model",
        "transcription.local_whisper.device",
        "transcription.local_whisper.compute_type",
        "transcription.local_whisper.language",
        "transcription.local_whisper.cpu_threads",
        "transcription.local_whisper.num_workers",
        "transcription.local_whisper.beam_size",
        "transcription.local_whisper.best_of",
        "transcription.local_whisper.temperature",
        "transcription.local_whisper.no_speech_threshold",
        "transcription.local_whisper.vad_filter",
        "transcription.local_whisper.vad_threshold",
        "transcription.local_whisper.vad_min_speech_ms",
        "transcription.local_whisper.vad_min_silence_ms",
        "transcription.local_whisper.condition_on_previous_text",
        "glossary_path",
    ),
    "画面": ("ui.topmost", "ui.follow_cursor", "ui.position", "ui.wave_gain"),
    "履歴とログ": (
        "history.enabled",
        "history.retention_days",
        "logging.retention_days",
        "logging.level",
    ),
    "API": ("api.port", "api.allowed_callback_hosts"),
}
"""まとまりごとの欄の並び。型から決まる部品はそのまま使い、型から決まらない部品は下の集合で決める。"""

HOTKEY_KEYS: frozenset[str] = frozenset(
    {"hotkeys.start", "hotkeys.pause", "hotkeys.cancel", "keyboard.paste_key"}
)
"""ホットキーの欄にするキー（出力先・送り先の hotkey は出力先の欄が同じ部品にする）。"""

SLIDER_KEYS: frozenset[str] = frozenset({"recording.volume_percent"})
"""つまみにするキー。"""

COMBO_KEYS: frozenset[str] = frozenset({"transcription.engine", "transcription.local_whisper.model"})
"""選択の欄にするキー。"""

OUTPUT_NAMES: dict[str, str] = {
    "paste_and_send": "貼り付けて送信",
    "paste_only": "貼り付けのみ",
    "copy_only": "コピーのみ",
    "ai_chat": "AI チャットへ送る",
}
"""出力先の ID ごとの画面の名前。"""

OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "paste_and_send": PasteAndSendSettings,
    "paste_only": PasteOnlySettings,
    "copy_only": CopyOnlySettings,
    "ai_chat": AiChatSettings,
}
"""出力先の ID ごとの設定のモデル（失敗の場所の判別子から既定の値を引く）。"""

MODIFIER_NAMES: dict[str, str] = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}
"""pynput の修飾キーの名前ごとの、画面の名前。"""

IGNORED_KEYS: frozenset[Qt.Key] = frozenset(
    {
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_AltGr,
        Qt.Key.Key_Tab,
        Qt.Key.Key_Backtab,
        Qt.Key.Key_Escape,
    }
)
"""ホットキーの組み合わせに入れないキー（修飾キーだけ・欄の移動の Tab・画面の取り消しの Esc）。"""

SPECIAL_KEY_NAMES: dict[Qt.Key, str] = {
    Qt.Key.Key_Space: "<space>",
    Qt.Key.Key_Return: "<enter>",
    Qt.Key.Key_Enter: "<enter>",
    Qt.Key.Key_Backspace: "<backspace>",
    Qt.Key.Key_Delete: "<delete>",
    Qt.Key.Key_Insert: "<insert>",
    Qt.Key.Key_Home: "<home>",
    Qt.Key.Key_End: "<end>",
    Qt.Key.Key_PageUp: "<page_up>",
    Qt.Key.Key_PageDown: "<page_down>",
    Qt.Key.Key_Up: "<up>",
    Qt.Key.Key_Down: "<down>",
    Qt.Key.Key_Left: "<left>",
    Qt.Key.Key_Right: "<right>",
}
"""文字でないキーの、pynput の書式での名前（F キーは別に扱う）。"""

FUNCTION_KEY_LAST: int = 24
"""ホットキーに使える F キーの最後の番号（F1〜F24）。"""

ASCII_PRINTABLE_FIRST: int = 0x21
ASCII_PRINTABLE_LAST: int = 0x7E
"""ホットキーに使う文字のキーの範囲（空白を除く ASCII の印字できる文字）。"""

HOTKEY_SEPARATOR: str = "+"
"""pynput の書式で、キーの組み合わせを区切る文字。"""

NUMBER_ERROR_TYPES: frozenset[str] = frozenset({"float_parsing", "int_parsing", "int_from_float"})
"""数値でない文字が入ったときの失敗の種類。"""

RANGE_ERROR_TYPES: frozenset[str] = frozenset(
    {"greater_than_equal", "less_than_equal", "greater_than", "less_than"}
)
"""数値が範囲の外のときの失敗の種類。"""


# === ホットキーの表示・読み取り ===


def format_hotkey(hotkey: str) -> str:
    """pynput の書式（`<ctrl>+<alt>+d`）を画面の形（`Ctrl+Alt+D`）にする。"""
    parts: list[str] = []
    for part in hotkey.split(HOTKEY_SEPARATOR):
        # `<...>` は修飾キーか名前のあるキー、そうでなければ文字のキー
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1]
            parts.append(
                MODIFIER_NAMES.get(name) or "".join(word.capitalize() for word in name.split("_"))
            )
        else:
            parts.append(part.upper())
    return HOTKEY_SEPARATOR.join(parts)


def parse_hotkey(combination: QKeyCombination) -> str | None:
    """ホットキーの欄で押されたキーの組み合わせを pynput の書式にする。修飾キーだけ・Tab・Esc は None。"""
    key = combination.key()
    # 修飾キーだけ・Tab・Esc は、組み合わせに入れない
    if key in IGNORED_KEYS:
        return None

    # 1. キーの名前を決める（F キー・名前のあるキー・文字のキー）
    function_number = key.value - Qt.Key.Key_F1.value + 1
    if 1 <= function_number <= FUNCTION_KEY_LAST:
        key_name = f"<f{function_number}>"
    elif key in SPECIAL_KEY_NAMES:
        key_name = SPECIAL_KEY_NAMES[key]
    elif ASCII_PRINTABLE_FIRST <= key.value <= ASCII_PRINTABLE_LAST and chr(key.value) != HOTKEY_SEPARATOR:
        key_name = chr(key.value).lower()
    else:
        return None

    # 2. 修飾キーを ctrl・alt・shift・cmd の順に前へ付ける
    modifiers = combination.keyboardModifiers()
    names = [
        name
        for name, modifier in (
            ("<ctrl>", Qt.KeyboardModifier.ControlModifier),
            ("<alt>", Qt.KeyboardModifier.AltModifier),
            ("<shift>", Qt.KeyboardModifier.ShiftModifier),
            ("<cmd>", Qt.KeyboardModifier.MetaModifier),
        )
        if modifiers & modifier
    ]
    return HOTKEY_SEPARATOR.join([*names, key_name])


# === 欄のエラーの文言 ===


def _field_info_at(location: tuple[int | str, ...]) -> FieldInfo | None:
    """pydantic の失敗の場所に当たる、設定のモデルの項目を引く（出力先の判別子の値から出力先のモデルを選ぶ）。"""
    model: Any = Settings
    info: FieldInfo | None = None
    for part in location:
        # 添字は何もせず、次の名前へ進む
        if isinstance(part, int):
            continue
        # 出力先の判別子の値なら、出力先のモデルに替える
        if part in OUTPUT_MODELS:
            model = OUTPUT_MODELS[part]
            continue
        # 一覧の項目なら、要素のモデルに替える
        if get_origin(model) is list:
            model = get_args(model)[0]
        fields = getattr(model, "model_fields", None)
        if fields is None or part not in fields:
            return None
        info = fields[part]
        model = info.annotation
    return info


def _range_text(info: FieldInfo) -> str:
    """項目の最小・最大の制限から、範囲の文言を作る。"""
    lower: Any = None
    upper: Any = None
    exclusive_lower = False
    for constraint in info.metadata:
        if hasattr(constraint, "ge"):
            lower = constraint.ge
        elif hasattr(constraint, "gt"):
            lower = constraint.gt
            exclusive_lower = True
        elif hasattr(constraint, "le"):
            upper = constraint.le
    if lower is not None and upper is not None:
        return f"{lower}〜{upper} の値を入れてください。"
    if lower is not None and exclusive_lower:
        return f"{lower} より大きい値を入れてください。"
    if lower is not None:
        return f"{lower} 以上の値を入れてください。"
    return f"{upper} 以下の値を入れてください。"


def to_field_message(
    error: Any, *, name_of: Callable[[str], str] = lambda key: key
) -> str:
    """pydantic の失敗 1 件を、画面設計「設定画面」の入力チェックの文言にする。

    name_of は設定のキーから欄の名前を引く関数（ホットキーが重なった欄の名前を出すのに使う）。
    """
    error_type = error["type"]
    info = _field_info_at(tuple(error["loc"]))
    if error_type in NUMBER_ERROR_TYPES and info is not None:
        return f"数値を入れてください（例: {info.get_default(call_default_factory=True)}）。"
    if error_type in RANGE_ERROR_TYPES and info is not None:
        return _range_text(info)
    if error_type == "string_too_short":
        return "送り先の名前を入れてください。"
    if error_type == "string_pattern_mismatch":
        return "http:// か https:// で始まる URL を入れてください。"
    if error_type == HOTKEY_OVERLAP_ERROR_TYPE:
        return f"「{name_of(error['ctx']['other'])}」と同じホットキーです。別のキーにしてください。"
    return str(error["msg"])


# === 確認ダイアログ ===


def _confirm(
    parent: QWidget,
    *,
    dialog_name: str,
    heading: str,
    body: str,
    accept_text: str,
    accept_name: str,
) -> bool:
    """見出しと本文の確認ダイアログを出し、受け入れる側のボタンが押されたかを返す。最初のフォーカスと Esc は戻る側。"""
    box = QMessageBox(parent)
    box.setObjectName(dialog_name)
    box.setWindowTitle(WINDOW_TITLE)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setText(heading)
    box.setInformativeText(body)
    accept = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    accept.setObjectName(accept_name)
    back = box.addButton("設定画面へ戻る", QMessageBox.ButtonRole.RejectRole)
    back.setObjectName("back_button")
    box.setDefaultButton(back)
    box.setEscapeButton(back)
    box.exec()
    return box.clickedButton() is accept


def confirm_discard(parent: QWidget, changed_count: int) -> bool:
    """変えた値を捨てて閉じるかを確かめる。捨てて閉じるなら True。"""
    return _confirm(
        parent,
        dialog_name="discard_dialog",
        heading="変えた値を捨てて閉じますか",
        body=f"保存していない変更が {changed_count} 件あります。閉じると、変えた値は保存されません。",
        accept_text="捨てて閉じる",
        accept_name="discard_button",
    )


def confirm_reset(parent: QWidget) -> bool:
    """全ての設定を既定に戻すかを確かめる。戻すなら True。"""
    return _confirm(
        parent,
        dialog_name="reset_dialog",
        heading="全ての設定を既定に戻しますか",
        body=(
            "出力先・ホットキー・AI チャットの送り先を含む全ての設定が既定の値になり、元に戻せません。"
            "「再起動で反映」の設定は、再起動するまで今の値で動きます。"
        ),
        accept_text="既定に戻す",
        accept_name="reset_button",
    )


# === ホットキーの欄 ===


class HotkeyEdit(QLineEdit):
    """押すと入力待ちになり、次に押したキーの組み合わせが入るホットキーの欄。

    画面では `Ctrl+Alt+D` の形で出し、値は pynput の書式で持つ。Tab と Esc は欄の移動と画面の取り消しに残す。
    """

    def __init__(self, hotkey: str) -> None:
        """今のホットキー（pynput の書式）で欄を作る。"""
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("キーを押してください")
        self._hotkey = hotkey
        self.setText(format_hotkey(hotkey) if hotkey else "")

    @property
    def hotkey(self) -> str:
        """今のホットキー（pynput の書式）。"""
        return self._hotkey

    def event(self, event: QEvent) -> bool:
        """Ctrl などを含む組み合わせが画面のショートカットに取られないよう、欄で受ける。"""
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt の名前
        """押された組み合わせを欄に入れる。組み合わせにならないキー（修飾キーだけ・Tab・Esc）は受けない。"""
        hotkey = parse_hotkey(event.keyCombination())
        if hotkey is None:
            event.ignore()
            return
        self._hotkey = hotkey
        self.setText(format_hotkey(hotkey))
        event.accept()


# === 設定画面 ===


class _TargetRow:
    """AI チャットの送り先の 1 行（出す・名前・URL・ホットキー・消すボタン）。"""

    def __init__(self, container: QWidget, fields: list[Field]) -> None:
        self.container = container
        self.fields = fields


class SettingsWindow(QWidget):
    """Settings のモデルから欄を組み立て、7 つのまとまりに並べ、保存で確かめてから書く設定画面。

    欄の名前は各項目の description、「再起動で反映」の印は json_schema_extra の reload から出す。
    まとまりと型から決まらない部品は FIELD_LAYOUT と各キーの集合で決める。
    """

    saved = Signal()
    """保存した（UiController.on_settings_saved へ）。"""

    restart_requested = Signal()
    """「保存して再起動」「今すぐ再起動」。"""

    closed = Signal()
    """窓が閉じた（保存・取り消し・窓の閉じるのどの経路でも。UiController.on_settings_closed へ）。"""

    def __init__(self, deps: UiDeps) -> None:
        """今の設定で欄を組み立てて窓を作る。"""
        super().__init__()
        self._deps = deps
        self._original = deps.get_settings()
        self._fields: list[Field] = []
        self._static: dict[str, Any] = {}
        self._target_rows: list[_TargetRow] = []
        self._targets_layout: QVBoxLayout | None = None
        self._ai_chat_index: int | None = None
        self._baseline: dict[str, Any] = {}
        self._restart_baseline: dict[str, Any] = {}
        self._force_close = False
        self.setObjectName("settings_window")
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumWidth(MIN_WIDTH_PX)
        self._build_frame()
        self._populate(self._original)
        self._restart_baseline = dict(self._baseline)

    # --- 窓の枠 ---

    def _build_frame(self) -> None:
        """まとまりのメニュー・エラーの一覧・欄の置き場・フッターを並べる（欄は _populate が入れる）。"""
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        self._group_menu = QListWidget()
        self._group_menu.setObjectName("group_menu")
        self._group_menu.setFixedWidth(160)
        self._group_menu.addItems(GROUP_NAMES)
        body.addWidget(self._group_menu)

        right = QVBoxLayout()
        body.addLayout(right, 1)

        self._error_summary = QFrame()
        self._error_summary.setObjectName("error_summary")
        self._error_summary.setProperty("role", "alert")
        self._error_summary.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._error_summary_layout = QVBoxLayout(self._error_summary)
        self._error_summary.hide()
        right.addWidget(self._error_summary)

        self._stack = QStackedWidget()
        right.addWidget(self._stack, 1)
        self._group_menu.currentRowChanged.connect(self._stack.setCurrentIndex)

        # 欄の変更で出す知らせ（再起動で反映・既定に戻した）
        self._restart_notice = QLabel()
        self._restart_notice.setObjectName("restart_notice")
        self._restart_notice.setProperty("role", "notice")
        self._restart_notice.setWordWrap(True)
        self._restart_notice.hide()
        self._reset_notice = QLabel()
        self._reset_notice.setObjectName("reset_notice")
        self._reset_notice.setProperty("role", "notice")
        self._reset_notice.setWordWrap(True)
        self._reset_notice.hide()
        self._restart_now_button = QPushButton("今すぐ再起動")
        self._restart_now_button.setObjectName("restart_now_button")
        self._restart_now_button.hide()
        self._restart_now_button.clicked.connect(self._restart_now)
        notices = QHBoxLayout()
        notices.addWidget(self._restart_notice, 1)
        notices.addWidget(self._reset_notice, 1)
        notices.addWidget(self._restart_now_button)
        root.addLayout(notices)

        # フッター: 左に既定に戻す、右にキャンセル・保存して再起動・保存
        footer = QHBoxLayout()
        reset_button = QPushButton("既定に戻す")
        reset_button.setObjectName("reset_button")
        reset_button.clicked.connect(self.reset_to_defaults)
        cancel_button = QPushButton("キャンセル")
        cancel_button.setObjectName("cancel_button")
        cancel_button.clicked.connect(self.try_close)
        self._save_and_restart_button = QPushButton("保存して再起動")
        self._save_and_restart_button.setObjectName("save_and_restart_button")
        self._save_and_restart_button.clicked.connect(lambda: self.save(restart=True))
        self._save_and_restart_button.hide()
        save_button = QPushButton("保存")
        save_button.setObjectName("save_button")
        save_button.setProperty("primary", True)
        save_button.clicked.connect(lambda: self.save(restart=False))
        footer.addWidget(reset_button)
        footer.addStretch(1)
        footer.addWidget(cancel_button)
        footer.addWidget(self._save_and_restart_button)
        footer.addWidget(save_button)
        root.addLayout(footer)

    # --- 欄の組み立て ---

    def _populate(self, settings: Settings) -> None:
        """設定の値で、まとまりごとの欄を組み立て直す。"""
        # 1. 前の欄を捨てる
        while self._stack.count():
            page = self._stack.widget(0)
            self._stack.removeWidget(page)
            page.deleteLater()
        self._fields = []
        self._static = {}
        self._target_rows = []
        self._targets_layout = None
        self._ai_chat_index = None

        # 2. まとまりごとの頁に、並びのとおり欄を足す
        for group, name in enumerate(GROUP_NAMES):
            layout = QVBoxLayout()
            layout.setSpacing(12)
            for key in FIELD_LAYOUT[name]:
                if key == OUTPUTS_FIELD_NAME:
                    self._add_outputs(layout, settings, group)
                elif key == "glossary_path":
                    self._add_glossary(layout, settings, group)
                else:
                    self._add_model_field(layout, settings, key, group)
            layout.addStretch(1)
            content = QWidget()
            content.setLayout(layout)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            self._stack.addWidget(scroll)

        # 3. 今の値を基準にして、知らせを直す
        self._group_menu.setCurrentRow(max(self._group_menu.currentRow(), 0))
        self._stack.setCurrentIndex(self._group_menu.currentRow())
        self._baseline = self._flat_values()
        self._refresh_notices()

    def _register(
        self,
        layout: QVBoxLayout,
        *,
        key: str,
        label: str,
        widget: QWidget,
        get: Callable[[], Any],
        group: int,
        extras: tuple[QWidget, ...] = (),
    ) -> Field:
        """欄 1 つ（名前・再起動で反映の印・設定のキー・部品・欄の下のエラー）を layout に足して登録する。"""
        reload = reload_of(key)
        widget.setObjectName(f"field_{key}")
        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        header = QHBoxLayout()
        name_label = QLabel(label)
        name_label.setProperty("role", "heading")
        header.addWidget(name_label)
        if reload == RELOAD_RESTART:
            badge = QLabel("再起動で反映")
            badge.setObjectName(f"restart_badge_{key}")
            badge.setProperty("role", "notice")
            header.addWidget(badge)
        header.addStretch(1)
        key_label = QLabel(key)
        key_label.setProperty("role", "mono")
        header.addWidget(key_label)
        column.addLayout(header)

        control = QHBoxLayout()
        control.addWidget(widget, 1)
        for extra in extras:
            control.addWidget(extra)
        column.addLayout(control)

        error_label = QLabel()
        error_label.setObjectName(f"error_{key}")
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()
        column.addWidget(error_label)

        layout.addWidget(row)
        field = Field(
            key=key,
            label=label,
            reload=reload,
            widget=widget,
            get=get,
            group=group,
            error_label=error_label,
        )
        self._fields.append(field)
        connect_changed(widget, self._on_field_changed)
        return field

    def _add_model_field(
        self, layout: QVBoxLayout, settings: Settings, key: str, group: int
    ) -> None:
        """設定のモデルの項目 1 つの欄を、項目の型から決めた部品で足す。"""
        info = self._model_field_info(key)
        value = value_at(settings, key)
        label = (info.description or key).split("。")[0]
        widget, get, extras = self._widget_for(key, info, value)
        self._register(
            layout, key=key, label=label, widget=widget, get=get, group=group, extras=extras
        )

    @staticmethod
    def _model_field_info(key: str) -> FieldInfo:
        """設定のキーに当たる、設定のモデルの項目を引く。"""
        info = _field_info_at(tuple(key_tokens(key)))
        if info is None:
            raise KeyError(f"設定のモデルに無いキーです（{key}）")
        return info

    @staticmethod
    def _widget_for(
        key: str, info: FieldInfo, value: Any
    ) -> tuple[QWidget, Callable[[], Any], tuple[QWidget, ...]]:
        """項目の型（と、型から決まらない部品のキー）から、部品・値を読む関数・部品の横に置くものを決める。"""
        annotation = info.annotation
        if key in HOTKEY_KEYS:
            hotkey_edit = HotkeyEdit(value)
            return hotkey_edit, lambda: hotkey_edit.hotkey, ()
        if key in SLIDER_KEYS:
            slider = make_slider(value)
            percent = QLabel(f"{slider.value()} %")
            slider.valueChanged.connect(lambda number: percent.setText(f"{number} %"))
            return slider, slider.value, (percent,)
        if key in COMBO_KEYS:
            choices = (
                WHISPER_MODEL_CHOICES if key.endswith("model") else tuple(get_args(annotation))
            )
            combo = make_combo(choices, value, editable=key.endswith("model"))
            return combo, combo.currentText, ()
        if annotation is bool:
            check_box = make_check_box("オン", value)
            return check_box, check_box.isChecked, ()
        if get_origin(annotation) is Literal:
            radios = make_radio_group(tuple(get_args(annotation)), value)
            return radios, lambda: selected_radio(radios), ()
        if annotation in (int, float, str):
            line = make_line_edit(str(value))
            return line, lambda: line.text().strip(), ()
        if annotation == list[str]:
            plain = make_plain_text(value)
            return plain, lambda: plain_text_lines(plain), ()
        raise TypeError(f"欄の部品を決められない型です（{key}: {annotation}）")

    def _add_glossary(self, layout: QVBoxLayout, settings: Settings, group: int) -> None:
        """用語集の CSV の欄（文字の欄と「選ぶ…」）を足す。空にすると設定ファイルと同じフォルダの用語集を使う。"""
        path = settings.glossary_path
        line = make_line_edit("" if path is None else str(path))
        pick_button = QPushButton("選ぶ…")
        pick_button.setObjectName("pick_glossary_button")

        def _pick() -> None:
            """ファイルを選ぶダイアログ（CSV）を開き、選んだパスを欄へ入れる。"""
            chosen, _filter = QFileDialog.getOpenFileName(
                self, "用語集の CSV を選ぶ", line.text(), "CSV (*.csv)"
            )
            if chosen:
                line.setText(chosen)

        pick_button.clicked.connect(_pick)
        self._register(
            layout,
            key="glossary_path",
            label="用語集の CSV（空は設定ファイルと同じフォルダの yogo.csv）",
            widget=line,
            get=lambda: line.text().strip() or None,
            group=group,
            extras=(pick_button,),
        )

    def _add_outputs(self, layout: QVBoxLayout, settings: Settings, group: int) -> None:
        """出力先ごとの欄（オン・ホットキー・送るまでの間・AI チャットの送り先の一覧）を足す。"""
        for index, output in enumerate(settings.outputs):
            prefix = f"{OUTPUTS_FIELD_NAME}[{index}]"
            name = OUTPUT_NAMES[output.id]
            self._static[f"{prefix}.id"] = output.id

            frame = QFrame()
            frame.setProperty("role", "surface")
            inner = QVBoxLayout(frame)

            enabled = make_check_box("オン", output.enabled)
            self._register(
                inner,
                key=f"{prefix}.enabled",
                label=name,
                widget=enabled,
                get=enabled.isChecked,
                group=group,
            )
            # 出力先ごとの確定のホットキー（AI チャットは送り先ごとに持つ）
            if not isinstance(output, AiChatSettings):
                hotkey_edit = HotkeyEdit(output.hotkey)
                self._register(
                    inner,
                    key=f"{prefix}.hotkey",
                    label=f"{name}のホットキー",
                    widget=hotkey_edit,
                    get=lambda edit=hotkey_edit: edit.hotkey,
                    group=group,
                )
            # 送るまでの間
            if isinstance(output, PasteAndSendSettings):
                self._add_delay(inner, prefix, "enter_delay_sec", output, group)
            if isinstance(output, AiChatSettings):
                self._add_delay(inner, prefix, "open_delay_sec", output, group)
                self._add_targets(inner, index, output, group)
            layout.addWidget(frame)

    def _add_delay(
        self,
        layout: QVBoxLayout,
        prefix: str,
        name: str,
        output: BaseModel,
        group: int,
    ) -> None:
        """出力先の、送るまでの間（秒）の数値の欄を足す。"""
        info = type(output).model_fields[name]
        line = make_line_edit(str(getattr(output, name)))
        self._register(
            layout,
            key=f"{prefix}.{name}",
            label=(info.description or name).split("。")[0],
            widget=line,
            get=lambda: line.text().strip(),
            group=group,
        )

    def _add_targets(
        self, layout: QVBoxLayout, index: int, output: AiChatSettings, group: int
    ) -> None:
        """AI チャットの送り先の一覧（1 行ずつ出す・名前・URL・ホットキー・消すボタン）と「送り先を足す」を足す。"""
        self._ai_chat_index = index
        self._static[f"{OUTPUTS_FIELD_NAME}[{index}].targets"] = []
        heading = QLabel("AI チャットの送り先")
        heading.setProperty("role", "heading")
        layout.addWidget(heading)
        table = QVBoxLayout()
        self._targets_layout = table
        layout.addLayout(table)
        for target in output.targets:
            self._add_target_row(target, group)
        add_button = QPushButton("送り先を足す")
        add_button.setObjectName("add_target_button")
        add_button.clicked.connect(lambda: self._add_new_target(group))
        layout.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_target_row(self, target: AiChatTarget, group: int) -> _TargetRow:
        """送り先の 1 行を一覧の末尾に足す。"""
        assert self._targets_layout is not None  # noqa: S101 送り先の一覧は出力先の欄と一緒に作る
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        line = QHBoxLayout()
        column.addLayout(line)

        enabled = make_check_box("出す", target.enabled)
        name = make_line_edit(target.name)
        name.setPlaceholderText("名前")
        url = make_line_edit(target.url)
        url.setPlaceholderText("https://")
        hotkey_edit = HotkeyEdit(target.hotkey)
        delete_button = QPushButton("消す")
        delete_button.setObjectName("delete_target_button")
        for widget in (enabled, name, url, hotkey_edit, delete_button):
            line.addWidget(widget)
        error_label = QLabel()
        error_label.setProperty("role", "error")
        error_label.setWordWrap(True)
        error_label.hide()
        column.addWidget(error_label)

        row_fields = [
            Field(
                key="",
                label="",
                reload=RELOAD_IMMEDIATE,
                widget=widget,
                get=get,
                group=group,
                error_label=error_label,
            )
            for widget, get in (
                (enabled, enabled.isChecked),
                (name, lambda: name.text().strip()),
                (url, lambda: url.text().strip()),
                (hotkey_edit, lambda: hotkey_edit.hotkey),
            )
        ]
        row = _TargetRow(container, row_fields)
        self._target_rows.append(row)
        self._targets_layout.addWidget(container)
        for widget in (enabled, name, url, hotkey_edit):
            connect_changed(widget, self._on_field_changed)
        delete_button.clicked.connect(lambda: self._remove_target_row(row))
        self._reindex_targets()
        return row

    def _add_new_target(self, group: int) -> None:
        """空の行（出すはオン）を一覧の末尾に足し、名前の欄へフォーカスを移す。"""
        row = self._add_target_row(AiChatTarget.model_construct(name="", url="", hotkey="", enabled=True), group)
        row.fields[1].widget.setFocus()
        self._on_field_changed()

    def _remove_target_row(self, row: _TargetRow) -> None:
        """送り先の行を一覧から消す。"""
        self._target_rows.remove(row)
        row.container.setParent(None)
        row.container.deleteLater()
        self._reindex_targets()
        self._on_field_changed()

    def _reindex_targets(self) -> None:
        """送り先の行の並びに合わせて、各欄のキー・名前・部品の名前を付け直す。"""
        if self._ai_chat_index is None:
            return
        for position, row in enumerate(self._target_rows):
            prefix = f"{OUTPUTS_FIELD_NAME}[{self._ai_chat_index}].targets[{position}]"
            for field, (attribute, label) in zip(
                row.fields,
                (
                    ("enabled", "出す"),
                    ("name", "名前"),
                    ("url", "URL"),
                    ("hotkey", "ホットキー"),
                ),
                strict=True,
            ):
                field.key = f"{prefix}.{attribute}"
                field.label = f"送り先 {position + 1} の{label}"
                field.widget.setObjectName(f"field_{field.key}")

    # --- 値の収集 ---

    def _all_fields(self) -> list[Field]:
        """全ての欄（送り先の行の欄を含む）を、並びの順に返す。"""
        return [*self._fields, *(field for row in self._target_rows for field in row.fields)]

    def _flat_values(self) -> dict[str, Any]:
        """全ての欄の値を、設定のキーごとに返す。"""
        values = {field.key: field.get() for field in self._all_fields()}
        values.update({key: value for key, value in self._static.items() if key.endswith(".id")})
        return values

    def collect(self) -> dict[str, Any]:
        """全ての欄の値を settings.toml と同じ形の dict にする。"""
        data: dict[str, Any] = {}
        # 一覧の要素は添字の順に作るため、出力先の ID と空の送り先の一覧を先に置く
        for key, value in self._static.items():
            set_nested(data, key, value)
        for field in self._all_fields():
            set_nested(data, field.key, field.get())
        return data

    def _changed_count(self) -> int:
        """保存していない変更の件数（開いたとき・保存したときの値から変えた欄の数）。"""
        current = self._flat_values()
        keys = set(current) | set(self._baseline)
        return sum(1 for key in keys if current.get(key) != self._baseline.get(key))

    def _restart_changed_count(self) -> int:
        """「再起動で反映」の欄のうち、開いたときの値から変えた欄の数。"""
        current = self._flat_values()
        return sum(
            1
            for field in self._all_fields()
            if field.reload == RELOAD_RESTART
            and current.get(field.key) != self._restart_baseline.get(field.key)
        )

    def _label_of(self, key: str) -> str:
        """設定のキーの欄の名前を返す（無ければキーのまま）。"""
        for field in self._all_fields():
            if field.key == key:
                return field.label
        return key

    # --- 知らせ・エラーの表示 ---

    def _on_field_changed(self) -> None:
        """欄を変えたら、既定に戻した知らせを消し、再起動の知らせを数え直す。"""
        self._reset_notice.hide()
        self._restart_now_button.hide()
        self._refresh_notices()

    def _refresh_notices(self) -> None:
        """再起動の知らせと「保存して再起動」を、再起動で反映の欄の変更に合わせて出す・隠す。"""
        # 既定に戻した知らせを出している間は、再起動の知らせを出さない
        count = 0 if not self._reset_notice.isHidden() else self._restart_changed_count()
        show = count > 0
        if show:
            self._restart_notice.setText(
                f"「再起動で反映」の設定を {count} 件変えました。"
                "「保存して再起動」で保存すると、すぐに効きます。"
            )
        self._restart_notice.setVisible(show)
        self._save_and_restart_button.setVisible(show)

    def _clear_errors(self) -> None:
        """前の保存で出したエラー（一覧・欄の下）を消す。"""
        while self._error_summary_layout.count():
            item = self._error_summary_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._error_summary.hide()
        for field in self._all_fields():
            if field.error_label is not None:
                field.error_label.clear()
                field.error_label.hide()
            field.widget.setProperty("invalid", False)
            field.widget.style().unpolish(field.widget)
            field.widget.style().polish(field.widget)

    def _show_errors(self, rows: list[tuple[str | None, str]]) -> None:
        """エラーの一覧（行 = 欄の名前: エラー。欄があれば行は欄へのリンク）を出し、欄の下にもエラーを出す。"""
        self._clear_errors()
        by_key = {field.key: field for field in self._all_fields()}
        field_count = len({key for key, _message in rows if key in by_key})
        title = (
            f"保存できませんでした。{field_count} 件の欄を直してください。"
            if field_count
            else "保存できませんでした。"
        )
        self._error_summary_layout.addWidget(QLabel(title))
        for key, message in rows:
            field = by_key.get(key) if key is not None else None
            if field is None:
                self._error_summary_layout.addWidget(QLabel(message))
                continue
            link = QLabel(f'<a href="{field.key}">{field.label}: {message}</a>')
            link.setTextFormat(Qt.TextFormat.RichText)
            link.linkActivated.connect(self._focus_field)
            self._error_summary_layout.addWidget(link)
            # 欄の下にも、同じ欄の失敗を重ねて出す
            if field.error_label is not None:
                previous = field.error_label.text()
                field.error_label.setText(f"{previous}\n{message}" if previous else message)
                field.error_label.show()
            field.widget.setProperty("invalid", True)
            field.widget.style().unpolish(field.widget)
            field.widget.style().polish(field.widget)
        self._error_summary.show()
        self._error_summary.setFocus()

    def _focus_field(self, key: str) -> None:
        """エラーの一覧の行から、その欄のまとまりへ切り替えて欄へフォーカスを移す。"""
        for field in self._all_fields():
            if field.key == key:
                self._group_menu.setCurrentRow(field.group)
                field.widget.setFocus()
                return

    # --- 操作 ---

    def save(self, *, restart: bool) -> bool:
        """欄の値を設定のモデルで確かめ、通れば書いて効かせる。通らなければエラーを出す。"""
        # 1. 欄の値を設定のモデルで確かめる（通らなければ欄ごとのエラーにして、入れた値は消さない）
        try:
            settings = Settings.model_validate(self.collect())
        except ValidationError as error:
            failures = [
                (
                    format_error_location(tuple(failure["loc"])),
                    to_field_message(failure, name_of=self._label_of),
                )
                for failure in error.errors()
            ]
            logger.info(f"設定画面の値が確かめに通らなかった（{', '.join(key for key, _ in failures)}）")
            self._show_errors(failures)
            return False

        # 2. 書いて効かせる（ホットキーを受け付けられない・書けないときは、エラーを出して閉じない）
        try:
            self._deps.save_settings(settings)
        except HotkeyError as error:
            logger.warning(f"保存するホットキーを受け付けられなかった（{error}）")
            self._show_errors(
                [(None, f"ホットキーを受け付けられませんでした（{error}）。別のキーにしてください。")]
            )
            return False
        except OSError as error:
            logger.exception("設定ファイルを書けなかった")
            self._show_errors([(None, f"設定ファイルを書けませんでした（{error}）")])
            return False

        # 3. 知らせ、再起動なら頼んで、窓を閉じる
        self._baseline = self._flat_values()
        self.saved.emit()
        if restart:
            self.restart_requested.emit()
        self._force_close = True
        self.close()
        return True

    def reset_to_defaults(self) -> None:
        """確かめて、戻すなら既定の設定を書いて欄に入れ、再起動が要る設定が変わっていれば件数と「今すぐ再起動」を出す。"""
        if not confirm_reset(self):
            return
        defaults = Settings()
        self._deps.save_settings(defaults)
        self._clear_errors()
        self._populate(defaults)
        self.saved.emit()

        # 開いたときの値から変わった「再起動で反映」の欄を数えて知らせる
        count = self._restart_changed_count()
        if count > 0:
            self._reset_notice.setText(
                f"既定に戻して保存しました。「再起動で反映」の設定 {count} 件は、再起動するまで前の値で動きます。"
            )
            self._reset_notice.show()
            self._restart_now_button.show()
            self._restart_notice.hide()
            self._save_and_restart_button.hide()

    def _restart_now(self) -> None:
        """設定画面を閉じて常駐アプリを再起動する。"""
        self.restart_requested.emit()
        self._force_close = True
        self.close()

    def try_close(self) -> bool:
        """欄を変えていなければ閉じ、変えていれば確かめて捨てるなら閉じる。閉じたかを返す。"""
        count = self._changed_count()
        if count > 0 and not confirm_discard(self, count):
            return False
        self._force_close = True
        self.close()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 Qt の名前
        """閉じる準備ができていれば閉じて知らせ、そうでなければ確かめる流れ（try_close）に回す。"""
        if self._force_close:
            event.accept()
            self.closed.emit()
            return
        event.ignore()
        self.try_close()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt の名前
        """Esc は「キャンセル」と同じ。"""
        if event.key() == Qt.Key.Key_Escape:
            self.try_close()
            return
        super().keyPressEvent(event)
