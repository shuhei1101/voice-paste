"""設定画面（トレイの「設定…」から開く）と、設定画面のホットキーの欄・確認ダイアログ・欄のエラーの文言。"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal, TypeAliasType, get_args, get_origin

from pydantic import ValidationError
from pydantic.fields import FieldInfo
from PySide6.QtCore import QEvent, QKeyCombination, Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
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
    GLOSSARIES_FIELD_NAME,
    GLOSSARY_NAME_OVERLAP_ERROR_TYPE,
    HINT_MAX_BYTES,
    HINT_PRESET_NAME_OVERLAP_ERROR_TYPE,
    HINT_PRESETS_FIELD_NAME,
    HINT_TOO_LONG_ERROR_TYPE,
    HINT_WORD_EMPTY_ERROR_TYPE,
    HINT_WORD_SEPARATOR_ERROR_TYPE,
    HOTKEY_OVERLAP_ERROR_TYPE,
    OUTPUTS_FIELD_NAME,
    PRESETS_FIELD_NAME,
    RELOAD_IMMEDIATE,
    RELOAD_RESTART,
    OutputSettingsBase,
    Settings,
    format_error_location,
)
from voice_paste.ui.windows.settings_fields import (
    SLIDER_MAX,
    WHISPER_MODEL_CHOICES,
    Field,
    checked_choices,
    connect_changed,
    key_tokens,
    make_check_box,
    make_check_box_group,
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
from voice_paste.ui.windows.settings_glossaries import (
    ROW_ERROR_MESSAGES,
    GlossaryField,
    GlossaryPanel,
)
from voice_paste.ui.windows.settings_hints import HintPresetPanel
from voice_paste.ui.windows.settings_presets import (
    PRESET_FIELD_LABELS,
    PRESET_MODELS,
    PresetListPanel,
)

if TYPE_CHECKING:
    from voice_paste.ui.controller import UiDeps

logger = logging.getLogger(__name__)

WINDOW_TITLE: str = "voice-paste の設定"
"""設定画面と確認ダイアログの窓の題。"""

MIN_WIDTH_PX: int = 720
"""設定画面の最小の幅（欄の名前と設定のキーが語の途中で折り返さない幅）。"""

PRESET_KIND_NAMES: dict[str, str] = {"browser": "ブラウザ添付", "endpoint": "エンドポイントへ送る"}
"""カスタムプリセットの種類ごとの画面の名前（設定画面のタブの名前）。種類の並びが、タブと録音の画面のボタンの並びになる。"""

GROUP_NAMES: tuple[str, ...] = (
    "出力先",
    *PRESET_KIND_NAMES.values(),
    "ホットキー",
    "録音",
    "文字起こし",
    "表記のヒント",
    "用語集",
    "画面",
    "履歴とログ",
    "API",
)
"""まとまりのメニューの並び（既定は先頭）。"""

FIELD_LAYOUT: dict[str, tuple[str, ...]] = {
    "出力先": (OUTPUTS_FIELD_NAME,),
    PRESET_KIND_NAMES["browser"]: (PRESETS_FIELD_NAME, "preset_options.browser.open_delay_sec"),
    PRESET_KIND_NAMES["endpoint"]: (PRESETS_FIELD_NAME, "preset_options.endpoint.timeout_sec"),
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
    ),
    "表記のヒント": (HINT_PRESETS_FIELD_NAME,),
    "用語集": (GLOSSARIES_FIELD_NAME,),
    "画面": (
        "ui.theme",
        "ui.topmost",
        "ui.follow_cursor",
        "ui.position",
        "ui.wave_gain",
        "ui.show_hotkeys",
    ),
    "履歴とログ": (
        "history.enabled",
        "history.retention_days",
        "logging.retention_days",
        "logging.level",
    ),
    "API": (
        "api.port",
        "api.allowed_callback_hosts",
        "api.continuous.min_silence_sec",
        "api.continuous.session_limit_sec",
    ),
}
"""まとまりごとの欄の並び。型から決まる部品はそのまま使い、型から決まらない部品は下の集合で決める。"""

HOTKEY_KEYS: frozenset[str] = frozenset(
    {"hotkeys.start", "hotkeys.pause", "hotkeys.cancel", "keyboard.paste_key"}
)
"""ホットキーの欄にするキー（出力先・プリセットの hotkey は出力先・プリセットの欄が同じ部品にする）。"""

SLIDER_KEYS: frozenset[str] = frozenset({"recording.volume_percent"})
"""つまみにするキー。"""

COMBO_KEYS: frozenset[str] = frozenset({"transcription.engine", "transcription.local_whisper.model"})
"""選択の欄にするキー。"""

OUTPUT_COMMON_FIELD_NAMES: frozenset[str] = frozenset(OutputSettingsBase.model_fields)
"""全ての出力先が持つ項目（id・enabled・hotkey）。出力先の欄はこれ以外の項目を、型から決めた部品で並べる。"""

OUTPUT_NOTE_KEY: str = "note"
"""項目の json_schema_extra で、欄の下に出す補助文を持つキー。"""

CHOICE_LABELS_KEY: str = "choice_labels"
"""項目の json_schema_extra のうち、リテラルの列挙の一覧のチェックボックスの名前（値 → 名前）を持つキー。"""

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

SAVED_HOTKEY_KEY: re.Pattern[str] = re.compile(
    rf"^(hotkeys\.\w+|{OUTPUTS_FIELD_NAME}\[\d+\]\.hotkey|{PRESETS_FIELD_NAME}\.\w+\[\d+\]\.hotkey)$"
)
"""保存した知らせでホットキーが変わったかを見る欄のキー（録音のホットキー・出力先とプリセットの確定のホットキー。貼り付けに送るキーは含めない）。"""

PRESET_KEY_PATTERN: re.Pattern[str] = re.compile(rf"^{PRESETS_FIELD_NAME}\[(\d+)\]\.(\w+)$")
"""プリセットの欄の失敗のキー（`presets[2].url`）を、設定の全体の中の添字と項目の名前に分ける。"""

GLOSSARY_KEY_PATTERN: re.Pattern[str] = re.compile(
    rf"^{GLOSSARIES_FIELD_NAME}\[(\d+)\]\.(?:(name)|rows\[(\d+)\]\.(wrong|right))$"
)
"""用語集の欄の失敗のキー（`glossaries[2].name`・`glossaries[2].rows[1].wrong`）を、何件目か・項目・何行目かに分ける。"""

GLOSSARY_FIELD_LABELS: dict[str, str] = {"name": "名前", "wrong": "誤変換", "right": "正しい表記"}
"""用語集の欄の名前（エラーの一覧に出す）。"""

GLOSSARY_NAME_HINT: str = "別の名前にしてください。"
"""名前が重なるときの欄の下の文言の末尾（エラーの一覧には出さない）。"""

HINT_KEY_PATTERN: re.Pattern[str] = re.compile(
    rf"^{HINT_PRESETS_FIELD_NAME}(?:\[(\d+)\]\.(?:(name)|words\[(\d+)\]))?$"
)
"""表記のヒントの欄の失敗のキー（`hint_presets`・`hint_presets[1].name`・`hint_presets[1].words[3]`）を、何件目か・項目・何つ目の語かに分ける。"""

HINT_LENGTH_LABEL: str = "有効なヒントの長さ"
"""有効なヒントの長さの失敗を、エラーの一覧に出す呼び方。"""

PRESET_URL_EXAMPLE: str = "https://example.com/hook"
"""プリセットの URL が空のときの文言に出す例。"""

OPTION_NOTES: dict[str, str] = {
    "preset_options.browser.open_delay_sec": "貼り付けてから Enter を送るまでの秒数は「出力先」の値を使う。",
    "preset_options.endpoint.timeout_sec": (
        "既定は 1.5 秒で、10 秒まで入れられる。この秒数で届かなければ、送り直さずにトレイで知らせる。"
    ),
}
"""欄の下に出す補助文（欄のキーごと）。"""


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


def _field_info_at(
    location: tuple[int | str, ...], settings_model: type[Settings]
) -> FieldInfo | None:
    """pydantic の失敗の場所に当たる、settings_model の項目を引く（判別子の値から出力先・プリセットのモデルを選ぶ）。"""
    model: Any = settings_model
    info: FieldInfo | None = None
    list_name: str | None = None
    previous: int | str | None = None
    for part in location:
        # 添字は何もせず、次の名前へ進む
        if isinstance(part, int):
            previous = part
            continue
        # 一覧の添字の次の名前が判別子の値なら、出力先・プリセットのモデルに替える
        if isinstance(previous, int):
            discriminated: Mapping[str, Any] = (
                settings_model.output_models
                if list_name == OUTPUTS_FIELD_NAME
                else PRESET_MODELS
            )
            if part in discriminated:
                model = discriminated[part]
                previous = part
                continue
        # 一覧の項目なら、要素のモデルに替える
        if get_origin(model) is list:
            model = get_args(model)[0]
        fields = getattr(model, "model_fields", None)
        if fields is None or part not in fields:
            return None
        info = fields[part]
        model = info.annotation
        list_name = part
        previous = part
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
    error: Any, *, model: type[Settings], name_of: Callable[[str], str] = lambda key: key
) -> str:
    """pydantic の失敗 1 件を、画面設計「設定画面」の入力チェックの文言にする。

    model は失敗の場所から項目（既定値・範囲）を引く設定のモデル。
    name_of は設定のキーから欄の名前を引く関数（ホットキーが重なった欄の名前を出すのに使う）。
    """
    error_type = error["type"]
    info = _field_info_at(tuple(error["loc"]), model)
    if error_type in NUMBER_ERROR_TYPES and info is not None:
        return f"数値を入れてください（例: {info.get_default(call_default_factory=True)}）。"
    if error_type in RANGE_ERROR_TYPES and info is not None:
        return _range_text(info)
    if error_type == "string_too_short":
        # 用語集の名前の空は名前を、プリセットのタイトルの空はタイトルを入れてもらう
        if error["loc"][:1] in ((GLOSSARIES_FIELD_NAME,), (HINT_PRESETS_FIELD_NAME,)):
            return "名前を入れてください。"
        return "タイトルを入れてください。"
    if error_type == GLOSSARY_NAME_OVERLAP_ERROR_TYPE:
        return f"用語集「{error['ctx']['name']}」と同じ名前です。{GLOSSARY_NAME_HINT}"
    if error_type == HINT_TOO_LONG_ERROR_TYPE:
        return (
            f"有効なヒントが長すぎます（{error['ctx']['length']} / {HINT_MAX_BYTES} バイト）。"
            "語を減らすか、プリセットを無効にしてください。"
        )
    if error_type == HINT_WORD_EMPTY_ERROR_TYPE:
        return "語を入れるか、この欄を消してください。"
    if error_type == HINT_WORD_SEPARATOR_ERROR_TYPE:
        return "読点（、）・句点（。）・改行は入れられません。語を分けて足してください。"
    if error_type == HINT_PRESET_NAME_OVERLAP_ERROR_TYPE:
        return f"プリセット「{error['ctx']['name']}」と同じ名前です。{GLOSSARY_NAME_HINT}"
    if error_type == "string_pattern_mismatch":
        # 空なら入れてもらい、空でなければ形を直してもらう
        if not error.get("input"):
            return f"URL を入れてください（例: {PRESET_URL_EXAMPLE}）。"
        return "http:// か https:// で始まる URL を入れてください。"
    if error_type == HOTKEY_OVERLAP_ERROR_TYPE:
        other = error["ctx"]["other"]
        # 重なった先がプリセットなら、プリセットの呼び方で示す
        if other.startswith(f"{PRESETS_FIELD_NAME}["):
            return f"{name_of(other)}と同じキーです。別のキーにしてください。"
        return f"「{name_of(other)}」と同じホットキーです。別のキーにしてください。"
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
            "出力先・ホットキーを含む全ての設定が既定の値になり、カスタムプリセットは全て消えます。"
            "元に戻せません。"
            "「再起動で反映」の設定は、再起動するまで今の値で動きます。"
        ),
        accept_text="既定に戻す",
        accept_name="reset_button",
    )


# === ホットキーの欄 ===


def field_object_name(key: str, widget: QWidget) -> str:
    """欄の部品の objectName（画面設計の項目 ID。ホットキーの欄は `hotkey_{キー}`、それ以外は `field_{キー}`）を返す。"""
    return f"{'hotkey' if isinstance(widget, HotkeyEdit) else 'field'}_{key}"


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

    def clear_hotkey(self) -> None:
        """ホットキーを空にする（空のホットキーは登録しない）。"""
        self._hotkey = ""
        self.setText("")

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


def _literal_choices(annotation: Any) -> tuple[str, ...] | None:
    """リテラルの列挙（`type` 文の別名を含む）の値を並びのまま返す。リテラルでなければ None。"""
    if isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if get_origin(annotation) is Literal:
        return tuple(get_args(annotation))
    return None


class SettingsWindow(QWidget):
    """Settings のモデルから欄を組み立て、まとまりに並べ、保存で確かめてから書く設定画面。

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
        self._settings_model = type(self._original)
        self._fields: list[Field] = []
        self._static: dict[str, Any] = {}
        self._panels: dict[str, PresetListPanel] = {}
        self._panel_groups: dict[str, int] = {}
        self._glossary_panel: GlossaryPanel | None = None
        self._glossary_group = GROUP_NAMES.index("用語集")
        self._hint_panel: HintPresetPanel | None = None
        self._hint_group = GROUP_NAMES.index("表記のヒント")
        self._baseline: dict[str, Any] = {}
        self._restart_baseline: dict[str, Any] = {}
        self._force_close = False
        self.setObjectName("settings_window")
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumWidth(MIN_WIDTH_PX)
        self._build_frame()
        self._populate(self._original)
        # 開いたときの値を「再起動で反映」の変更の基準にして、知らせを数え直す
        self._restart_baseline = dict(self._baseline)
        self._refresh_notices()

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

        # 欄の変更・保存で出す知らせ（再起動で反映・既定に戻した・保存した）
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
        self._saved_notice = QLabel()
        self._saved_notice.setObjectName("saved_notice")
        self._saved_notice.setProperty("role", "notice")
        self._saved_notice.setWordWrap(True)
        self._saved_notice.hide()
        self._restart_now_button = QPushButton("今すぐ再起動")
        self._restart_now_button.setObjectName("restart_now_button")
        self._restart_now_button.hide()
        self._restart_now_button.clicked.connect(self._restart_now)
        notices = QHBoxLayout()
        notices.addWidget(self._restart_notice, 1)
        notices.addWidget(self._reset_notice, 1)
        notices.addWidget(self._saved_notice, 1)
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
        self._panels = {}
        self._panel_groups = {}
        self._glossary_panel = None
        self._hint_panel = None

        # 2. まとまりごとの頁に、並びのとおり欄を足す
        for group, name in enumerate(GROUP_NAMES):
            layout = QVBoxLayout()
            layout.setSpacing(12)
            for key in FIELD_LAYOUT[name]:
                if key == OUTPUTS_FIELD_NAME:
                    self._add_outputs(layout, settings, group)
                elif key == PRESETS_FIELD_NAME:
                    self._add_presets(layout, settings, name, group)
                elif key == GLOSSARIES_FIELD_NAME:
                    self._add_glossaries(layout, settings)
                elif key == HINT_PRESETS_FIELD_NAME:
                    self._add_hints(layout, settings)
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
        widget.setObjectName(field_object_name(key, widget))
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
        error_label.setTextFormat(Qt.TextFormat.PlainText)
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
        self._add_note(layout, OPTION_NOTES.get(key))

    @staticmethod
    def _add_note(layout: QVBoxLayout, note: str | None) -> None:
        """欄の下に補助文を出す（補助文が無ければ何もしない）。"""
        if note is None:
            return
        label = QLabel(note)
        label.setProperty("role", "muted")
        label.setWordWrap(True)
        layout.addWidget(label)

    def _model_field_info(self, key: str) -> FieldInfo:
        """設定のキーに当たる、設定のモデルの項目を引く。"""
        info = _field_info_at(tuple(key_tokens(key)), self._settings_model)
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
            extra = info.json_schema_extra
            labels = extra.get(CHOICE_LABELS_KEY) if isinstance(extra, dict) else None
            radios = make_radio_group(tuple(get_args(annotation)), value, labels=labels)
            return radios, lambda: selected_radio(radios), ()
        if get_origin(annotation) is list and (choices := _literal_choices(get_args(annotation)[0])):
            # リテラルの列挙の一覧は、値ごとのチェックボックスを横に並べる
            extra = info.json_schema_extra
            labels = extra.get(CHOICE_LABELS_KEY, {}) if isinstance(extra, dict) else {}
            check_boxes = make_check_box_group(key, choices, labels, value)
            return check_boxes, lambda: checked_choices(check_boxes), ()
        if annotation in (int, float, str):
            line = make_line_edit(str(value))
            return line, lambda: line.text().strip(), ()
        if annotation == list[str]:
            plain = make_plain_text(value)
            return plain, lambda: plain_text_lines(plain), ()
        raise TypeError(f"欄の部品を決められない型です（{key}: {annotation}）")

    def _add_glossaries(self, layout: QVBoxLayout, settings: Settings) -> None:
        """用語集の一覧と、選んだ用語集の名前の欄・行の表を足す。補正に使う用語集は設定の active_glossary（無ければ 1 件目）。"""
        glossaries = self._deps.list_glossaries()
        names = [glossary.name for glossary in glossaries]
        active = settings.active_glossary if settings.active_glossary in names else names[0]
        panel = GlossaryPanel(self._deps.read_glossary, self._deps.new_glossary_path)
        panel.set_glossaries(glossaries, active)
        panel.changed.connect(self._on_field_changed)
        self._glossary_panel = panel
        layout.addWidget(panel)

    def _add_hints(self, layout: QVBoxLayout, settings: Settings) -> None:
        """表記のヒントの長さとプリセットの一覧を足す。"""
        panel = HintPresetPanel()
        panel.set_presets(settings.hint_presets)
        panel.changed.connect(self._on_field_changed)
        self._hint_panel = panel
        layout.addWidget(panel)

    def _add_outputs(self, layout: QVBoxLayout, settings: Settings, group: int) -> None:
        """出力先ごとの欄（オン・確定のホットキーと、その出力先のモデルが持つ固有の項目）を足す。"""
        for index, output in enumerate(settings.outputs):
            prefix = f"{OUTPUTS_FIELD_NAME}[{index}]"
            name = self._deps.output_titles[output.id]
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
            # 出力先ごとの確定のホットキー
            hotkey_edit = HotkeyEdit(output.hotkey)
            self._register(
                inner,
                key=f"{prefix}.hotkey",
                label=f"{name}のホットキー",
                widget=hotkey_edit,
                get=lambda edit=hotkey_edit: edit.hotkey,
                group=group,
            )
            # その出力先のモデルだけが持つ項目（貼り付けて送信の送るまでの間など）
            for field_name, info in type(output).model_fields.items():
                if field_name not in OUTPUT_COMMON_FIELD_NAMES:
                    self._add_output_field(inner, prefix, field_name, info, output, group)
            layout.addWidget(frame)

    def _add_output_field(
        self,
        layout: QVBoxLayout,
        prefix: str,
        name: str,
        info: FieldInfo,
        output: OutputSettingsBase,
        group: int,
    ) -> None:
        """出力先に固有の項目 1 つの欄を、項目の型から決めた部品で足す（補助文があれば欄の下に出す）。"""
        key = f"{prefix}.{name}"
        widget, get, extras = self._widget_for(key, info, getattr(output, name))
        self._register(
            layout,
            key=key,
            label=(info.description or name).split("。")[0],
            widget=widget,
            get=get,
            group=group,
            extras=extras,
        )
        extra = info.json_schema_extra
        note = extra.get(OUTPUT_NOTE_KEY) if isinstance(extra, dict) else None
        self._add_note(layout, note if isinstance(note, str) else None)

    def _add_presets(
        self, layout: QVBoxLayout, settings: Settings, group_name: str, group: int
    ) -> None:
        """タブの種類のカスタムプリセットの一覧（足す・消す・並べ替え）を足す。"""
        kind = next(kind for kind, name in PRESET_KIND_NAMES.items() if name == group_name)
        panel = PresetListPanel(kind)
        panel.set_presets([preset for preset in settings.presets if preset.kind == kind])
        panel.changed.connect(self._on_field_changed)
        self._panels[kind] = panel
        self._panel_groups[kind] = group
        layout.addWidget(panel)

    # --- 値の収集 ---

    @property
    def _glossaries_panel(self) -> GlossaryPanel:
        """用語集のまとまりの部品を返す（欄を組み立てた後に使う）。"""
        if self._glossary_panel is None:
            raise RuntimeError("用語集の部品がまだ無い")
        return self._glossary_panel

    @property
    def _hints_panel(self) -> HintPresetPanel:
        """表記のヒントのまとまりの部品を返す（欄を組み立てた後に使う）。"""
        if self._hint_panel is None:
            raise RuntimeError("表記のヒントの部品がまだ無い")
        return self._hint_panel

    def _all_fields(self) -> list[Field]:
        """プリセットの一覧を除く全ての欄を、並びの順に返す。"""
        return list(self._fields)

    def _preset_values(self) -> list[tuple[str, int, dict[str, Any]]]:
        """全てのプリセットを（種類, そのタブの中の何件目か, 値）で、設定の presets の並び（種類の並びの順）で返す。"""
        return [
            (kind, position, item)
            for kind in PRESET_KIND_NAMES
            if kind in self._panels
            for position, item in enumerate(self._panels[kind].collect())
        ]

    def _flat_values(self) -> dict[str, Any]:
        """全ての欄の値を、設定のキーごとに返す（プリセットは種類・何件目・項目ごと）。"""
        values = {field.key: field.get() for field in self._all_fields()}
        values.update({key: value for key, value in self._static.items() if key.endswith(".id")})
        # 用語集は、一覧（名前・場所・並び）・補正に使う用語集・行を変えた用語集の行をそれぞれ 1 件として数える
        if self._glossary_panel is not None:
            values[GLOSSARIES_FIELD_NAME] = [
                (item["name"], str(item["path"])) for item in self._glossary_panel.collect()
            ]
            values["active_glossary"] = self._glossary_panel.active_name()
            values["glossary_rows"] = self._glossary_panel.changed_rows()
        # 表記のヒントは、プリセットの一覧（名前・語・有効か・並び）を 1 件として数える
        if self._hint_panel is not None:
            values[HINT_PRESETS_FIELD_NAME] = self._hint_panel.collect()
        for kind, position, item in self._preset_values():
            values.update(
                {f"{PRESETS_FIELD_NAME}.{kind}[{position}].{name}": value for name, value in item.items()}
            )
        return values

    def collect(self) -> dict[str, Any]:
        """全ての欄の値を settings.toml と同じ形の dict にする。"""
        data: dict[str, Any] = {}
        # 一覧の要素は添字の順に作るため、出力先の ID と空の送り先の一覧を先に置く
        for key, value in self._static.items():
            set_nested(data, key, value)
        for field in self._all_fields():
            set_nested(data, field.key, field.get())
        # プリセットは、種類のタブの並びの順に 1 つの一覧にする
        data[PRESETS_FIELD_NAME] = [item for _kind, _position, item in self._preset_values()]
        # 用語集は、一覧と補正に使う用語集を入れる（glossary_path は置かない）
        data[GLOSSARIES_FIELD_NAME] = self._glossaries_panel.collect()
        data["active_glossary"] = self._glossaries_panel.active_name()
        # 表記のヒントは、プリセットの一覧を入れる
        data[HINT_PRESETS_FIELD_NAME] = self._hints_panel.collect()
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

    def _locate_preset(self, key: str) -> tuple[str, int, str, str] | None:
        """プリセットの欄のキー（`presets[2].url`）を、（種類, そのタブの中の何件目か, 項目の名前, タイトル）にする。プリセットの欄でなければ None。"""
        matched = PRESET_KEY_PATTERN.match(key)
        if matched is None or matched.group(2) not in PRESET_FIELD_LABELS:
            return None
        presets = self._preset_values()
        index = int(matched.group(1))
        if index >= len(presets):
            return None
        kind, position, item = presets[index]
        return kind, position, matched.group(2), str(item["title"])

    @staticmethod
    def _locate_glossary(key: str) -> tuple[int, GlossaryField, int | None] | None:
        """用語集の欄のキー（`glossaries[2].name`・`glossaries[2].rows[1].wrong`）を、（何件目か, 項目, 何行目か）にする。用語集の欄でなければ None。"""
        matched = GLOSSARY_KEY_PATTERN.match(key)
        if matched is None:
            return None
        position = int(matched.group(1))
        if matched.group(2):
            return position, "name", None
        field: GlossaryField = "wrong" if matched.group(4) == "wrong" else "right"
        return position, field, int(matched.group(3))

    @staticmethod
    def _locate_hint(key: str) -> tuple[int | str, ...] | None:
        """表記のヒントの欄のキーを、HintPresetPanel の失敗の場所（`()`・`(1, "name")`・`(1, "words", 3)`）にする。表記のヒントの欄でなければ None。"""
        matched = HINT_KEY_PATTERN.match(key)
        if matched is None:
            return None
        # 場所が hint_presets だけ: 有効なヒントの長さ
        if matched.group(1) is None:
            return ()
        position = int(matched.group(1))
        if matched.group(2):
            return (position, "name")
        return (position, "words", int(matched.group(3)))

    @staticmethod
    def _hint_label(location: tuple[int | str, ...]) -> str:
        """エラーの一覧に出す表記のヒントの欄の呼び方（「有効なヒントの長さ」「プリセット 1 件目の名前」「プリセット 1 件目の 2 つ目の語」）を返す。"""
        if not location:
            return HINT_LENGTH_LABEL
        position = int(location[0]) + 1
        if location[1] == "name":
            return f"プリセット {position} 件目の名前"
        return f"プリセット {position} 件目の {int(location[2]) + 1} つ目の語"

    @staticmethod
    def _glossary_label(position: int, field: GlossaryField, row: int | None) -> str:
        """エラーの一覧に出す用語集の欄の呼び方（「用語集 3 件目の名前」「用語集 3 件目の 2 行目の誤変換」）を返す。"""
        if row is None:
            return f"用語集 {position + 1} 件目の{GLOSSARY_FIELD_LABELS[field]}"
        return f"用語集 {position + 1} 件目の {row + 1} 行目の{GLOSSARY_FIELD_LABELS[field]}"

    @staticmethod
    def _preset_name(position: int, title: str) -> str:
        """プリセットの呼び方（タイトルがあれば「タイトル」、空ならそのタブの中の何件目か）。"""
        return f"プリセット「{title}」" if title else f"プリセット {position + 1} 件目"

    def _label_of(self, key: str, relative_to: str | None = None) -> str:
        """設定のキーの欄の名前を返す（無ければキーのまま）。プリセットは、relative_to のキーと別の種類なら種類も添える。"""
        located = self._locate_preset(key)
        if located is not None:
            kind, position, _attribute, title = located
            name = self._preset_name(position, title)
            own = self._locate_preset(relative_to) if relative_to is not None else None
            if own is not None and own[0] != kind:
                return f"「{PRESET_KIND_NAMES[kind]}」の{name}"
            return name
        for field in self._all_fields():
            if field.key == key:
                return field.label
        return key

    # --- 知らせ・エラーの表示 ---

    def _on_field_changed(self) -> None:
        """欄を変えたら、既定に戻した知らせと保存した知らせを消し、再起動の知らせを数え直す。"""
        self._reset_notice.hide()
        self._saved_notice.hide()
        self._restart_now_button.hide()
        self._refresh_notices()

    def _refresh_notices(self) -> None:
        """再起動の知らせと「保存して再起動」を、再起動で反映の欄の変更に合わせて出す・隠す。"""
        # 既定に戻した知らせか保存した知らせを出している間は、再起動の知らせを出さない
        notice_shown = not self._reset_notice.isHidden() or not self._saved_notice.isHidden()
        count = 0 if notice_shown else self._restart_changed_count()
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
        for panel in self._panels.values():
            panel.clear_errors()
        if self._glossary_panel is not None:
            self._glossary_panel.clear_errors()
        if self._hint_panel is not None:
            self._hint_panel.clear_errors()
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
        field_count = len(
            {
                key
                for key, _message in rows
                if key is not None
                and (
                    key in by_key
                    or self._locate_preset(key) is not None
                    or self._locate_glossary(key) is not None
                    or self._locate_hint(key) is not None
                )
            }
        )
        title = (
            f"保存できませんでした。{field_count} 件の欄を直してください。"
            if field_count
            else "保存できませんでした。"
        )
        self._error_summary_layout.addWidget(self._plain_label(title))
        for key, message in rows:
            field = by_key.get(key) if key is not None else None
            located = self._locate_preset(key) if key is not None else None
            # プリセットの欄: 一覧の行（欄へのリンク）と、欄の下のエラーを出す
            if located is not None and key is not None:
                kind, position, attribute, title = located
                label = f"{self._preset_name(position, title)}の{PRESET_FIELD_LABELS[attribute]}"
                link = QLabel(f'<a href="{key}">{html.escape(f"{label}: {message}")}</a>')
                link.setTextFormat(Qt.TextFormat.RichText)
                link.linkActivated.connect(self._focus_field)
                self._error_summary_layout.addWidget(link)
                self._panels[kind].show_error(position, attribute, message)
                continue
            glossary_located = self._locate_glossary(key) if key is not None else None
            # 用語集の欄: 一覧の行（欄へのリンク）と、欄の下のエラーを出す
            if glossary_located is not None and key is not None:
                position, glossary_field, glossary_row = glossary_located
                label = self._glossary_label(position, glossary_field, glossary_row)
                # 名前の重なりは、一覧には「別の名前にしてください。」を添えない
                summary = message.removesuffix(f"。{GLOSSARY_NAME_HINT}")
                link = QLabel(f'<a href="{key}">{html.escape(f"{label}: {summary}")}</a>')
                link.setTextFormat(Qt.TextFormat.RichText)
                link.linkActivated.connect(self._focus_field)
                self._error_summary_layout.addWidget(link)
                self._glossaries_panel.show_error(
                    position, glossary_field, message, row=glossary_row
                )
                continue
            hint_located = self._locate_hint(key) if key is not None else None
            # 表記のヒントの欄: 一覧の行（欄へのリンク）と、欄の下のエラーを出す
            if hint_located is not None and key is not None:
                label = self._hint_label(hint_located)
                # 名前の重なりは、一覧には「別の名前にしてください。」を添えない
                summary = message.removesuffix(f"。{GLOSSARY_NAME_HINT}")
                link = QLabel(f'<a href="{key}">{html.escape(f"{label}: {summary}")}</a>')
                link.setTextFormat(Qt.TextFormat.RichText)
                link.linkActivated.connect(self._focus_field)
                self._error_summary_layout.addWidget(link)
                self._hints_panel.show_error(hint_located, message)
                continue
            if field is None:
                self._error_summary_layout.addWidget(self._plain_label(message))
                continue
            link = QLabel(f'<a href="{field.key}">{html.escape(f"{field.label}: {message}")}</a>')
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

    @staticmethod
    def _plain_label(text: str) -> QLabel:
        """書式を解釈しない（`<ctrl>` などの山括弧を文字のまま出す）ラベルを作る。"""
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _focus_field(self, key: str) -> None:
        """エラーの一覧の行から、その欄のまとまりへ切り替えて欄へフォーカスを移す。"""
        glossary_located = self._locate_glossary(key)
        # 用語集の欄: 用語集のまとまりへ切り替えて、その用語集の行の表を出して欄へフォーカスを移す
        if glossary_located is not None:
            self._group_menu.setCurrentRow(self._glossary_group)
            position, glossary_field, glossary_row = glossary_located
            self._glossaries_panel.focus_field(position, glossary_field, row=glossary_row)
            return
        hint_located = self._locate_hint(key)
        # 表記のヒントの欄: 表記のヒントのまとまりへ切り替えて、欄へフォーカスを移す
        if hint_located is not None:
            self._group_menu.setCurrentRow(self._hint_group)
            self._hints_panel.focus_field(hint_located)
            return
        located = self._locate_preset(key)
        # プリセットの欄: その種類のタブへ切り替えて、一覧の欄へフォーカスを移す
        if located is not None:
            kind, position, attribute, _title = located
            self._group_menu.setCurrentRow(self._panel_groups[kind])
            self._panels[kind].focus_field(position, attribute)
            return
        for field in self._all_fields():
            if field.key == key:
                self._group_menu.setCurrentRow(field.group)
                field.widget.setFocus()
                return

    # --- 操作 ---

    def save(self, *, restart: bool) -> bool:
        """欄の値を設定のモデルで確かめ、通れば書いて効かせ、窓を開いたまま保存した知らせを出す（restart のときだけ閉じる）。通らなければエラーを出す。"""
        # 1. 欄の値を設定のモデルと、用語集の行（誤変換か正しい表記の片方だけが空）で確かめる（通らなければ欄ごとのエラーにして、入れた値は消さない）
        failures: list[tuple[str, str]] = []
        settings: Settings | None = None
        try:
            settings = self._settings_model.model_validate(self.collect())
        except ValidationError as error:
            failures = [
                (
                    format_error_location(tuple(failure["loc"])),
                    to_field_message(
                        failure,
                        model=self._settings_model,
                        name_of=lambda other, own=format_error_location(tuple(failure["loc"])): (
                            self._label_of(other, own)
                        ),
                    ),
                )
                for failure in error.errors()
            ]
        failures += [
            (f"{GLOSSARIES_FIELD_NAME}[{position}].rows[{row}].{field}", ROW_ERROR_MESSAGES[field])
            for position, row, field in self._glossaries_panel.row_errors()
        ]
        if settings is None or failures:
            logger.info(f"設定画面の値が確かめに通らなかった（{', '.join(key for key, _ in failures)}）")
            self._show_errors(failures)
            return False

        # 2. 書いて効かせる（ホットキーを受け付けられない・書けないときは、エラーを出して知らせを出さない）
        try:
            self._deps.save_settings(settings, self._glossaries_panel.changed_rows())
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

        # 3. 保存した行・値を「変えていない」の基準に置き直す（`_baseline` は用語集の changed_rows を含むため、用語集の基準を先に置き直す）
        self._glossaries_panel.mark_saved()
        self._baseline = self._flat_values()
        self.saved.emit()

        # 4. 再起動なら頼んで窓を閉じ、そうでなければ窓を開いたまま保存した知らせを出す
        if restart:
            self.restart_requested.emit()
            self._force_close = True
            self.close()
            return True
        self._show_saved_notice()
        return True

    def _show_saved_notice(self) -> None:
        """保存した知らせを出す。新しいホットキーが閉じると効くことと、「再起動で反映」の欄の件数を、変えたときだけ続ける。"""
        text = "保存しました。"
        # ホットキーの欄が開いたときの値から変わっていれば、閉じると効くことを添える
        if self._hotkey_changed():
            text += "新しいホットキーは、設定画面を閉じると効きます。"
        # 「再起動で反映」の欄が開いたときの値から変わっていれば、件数と今すぐ再起動を出し、再起動の知らせを隠す
        count = self._restart_changed_count()
        if count > 0:
            text += f"「再起動で反映」の設定 {count} 件は、再起動するまで前の値で動きます。"
        self._restart_now_button.setVisible(count > 0)
        self._saved_notice.setText(text)
        self._saved_notice.show()
        # 画面を見ない利用者にも、同じ文を読み上げで伝える
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self._saved_notice, text))
        self._reset_notice.hide()
        self._refresh_notices()

    def _hotkey_changed(self) -> bool:
        """閉じたときに張り直すホットキーの欄（`keyboard.paste_key` は含めない）が、開いたときの値から変わったかを返す。"""
        current = self._flat_values()
        keys = {
            key for key in current.keys() | self._restart_baseline.keys() if SAVED_HOTKEY_KEY.match(key)
        }
        return any(
            (current.get(key) or "") != (self._restart_baseline.get(key) or "") for key in keys
        )

    def reset_to_defaults(self) -> None:
        """確かめて、戻すなら既定の設定を書いて欄に入れ、再起動が要る設定が変わっていれば件数と「今すぐ再起動」を出す。"""
        if not confirm_reset(self):
            return
        defaults = self._settings_model()
        self._deps.save_settings(defaults, {})
        self._clear_errors()
        self._saved_notice.hide()
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

    def _confirm_close(self) -> bool:
        """欄を変えていなければそのまま、変えていれば確かめて、閉じてよいかを返す。"""
        count = self._changed_count()
        return count == 0 or confirm_discard(self, count)

    def try_close(self) -> bool:
        """欄を変えていなければ閉じ、変えていれば確かめて捨てるなら閉じる。閉じたかを返す。"""
        if not self._confirm_close():
            return False
        self._force_close = True
        self.close()
        return True

    def close_without_confirm(self) -> None:
        """変えた値を捨てる確認を出さずに閉じる（変えた値は保存しない）。アプリの終了・再起動のときに UiController が呼ぶ。"""
        self._force_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 Qt の名前
        """閉じる準備ができているか、確かめて閉じてよければ閉じて知らせる。"""
        if self._force_close or self._confirm_close():
            event.accept()
            self.closed.emit()
        else:
            event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 Qt の名前
        """Esc は「キャンセル」と同じ。"""
        if event.key() == Qt.Key.Key_Escape:
            self.try_close()
            return
        super().keyPressEvent(event)
