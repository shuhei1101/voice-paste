"""設定のモデル（pydantic）と、settings.toml の読み書き（tomlkit）。"""

from __future__ import annotations

import copy
import logging
import operator
import os
import re
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from functools import reduce
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Protocol

import tomlkit
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    ValidationError,
    create_model,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError
from tomlkit.container import Container
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import AoT, Comment, Item, Key, Null, Table, Whitespace

from voice_paste.shared.errors import SettingsError

logger = logging.getLogger(__name__)

RELOAD_IMMEDIATE: str = "immediate"
"""設定画面で保存すると、動いている常駐アプリに効く項目の印。"""

RELOAD_RESTART: str = "restart"
"""再起動してから効く項目の印。"""

OUTPUTS_FIELD_NAME: str = "outputs"
"""出力先の一覧を持つ Settings の項目名。"""

PRESETS_FIELD_NAME: str = "presets"
"""カスタムプリセットの一覧を持つ Settings の項目名。"""

DISCRIMINATED_LIST_FIELD_NAMES: tuple[str, ...] = (OUTPUTS_FIELD_NAME, PRESETS_FIELD_NAME)
"""判別共用体の一覧を持つ Settings の項目名。失敗の場所に添字の次の判別子の値が入る。"""

OUTPUT_DISCRIMINATOR_INDEX: int = 2
"""判別共用体の一覧の失敗の場所（項目名・添字・判別子の値・…）で、判別子の値が入る位置。"""

HOTKEY_OVERLAP_ERROR_TYPE: str = "hotkey_overlap"
"""ホットキーが重なるときの ValidationError の種類。理由の文に先のキーを `other` として持つ。"""

GLOSSARY_NAME_OVERLAP_ERROR_TYPE: str = "glossary_name_overlap"
"""用語集の名前が重なるときの ValidationError の種類。理由の文に重なった名前を `name` として持つ。"""

GLOSSARIES_FIELD_NAME: str = "glossaries"
"""用語集の一覧を持つ Settings の項目名。"""

GLOSSARY_PRESET_NAME_OVERLAP_ERROR_TYPE: str = "glossary_preset_name_overlap"
"""用語集のプリセットの名前が重なるときの ValidationError の種類。理由の文に重なった名前を `name` として持つ。"""

GLOSSARY_PRESETS_FIELD_NAME: str = "glossary_presets"
"""用語集のプリセットの一覧を持つ Settings の項目名。"""

HINT_PRESETS_FIELD_NAME: str = "hint_presets"
"""表記のヒントのプリセットの一覧を持つ Settings の項目名。"""

HINT_MAX_BYTES: int = 222
"""有効なプリセットの語をつないだ手がかりの UTF-8 のバイト数の上限。

faster-whisper が hotwords を先頭の 223 トークンに切ることから、頭に足す空白の 1 バイトを引いた値。
Whisper のトークンは 1 バイト以上を表すため、バイト数で数えれば上限を守れる。
"""

HINT_SEPARATOR: str = "、"
"""手がかりの語の間に入れる区切り。"""

HINT_WORD_FORBIDDEN_CHARS: tuple[str, ...] = (HINT_SEPARATOR, "。", "\n", "\r")
"""語に含められない文字（区切り・句点・改行）。"""

HINT_TOO_LONG_ERROR_TYPE: str = "hint_too_long"
"""有効な手がかりが上限を超えるときの ValidationError の種類。今のバイト数を `length` として持つ。"""

HINT_WORD_EMPTY_ERROR_TYPE: str = "hint_word_empty"
"""手がかりの語が空のときの ValidationError の種類。"""

HINT_WORD_SEPARATOR_ERROR_TYPE: str = "hint_word_separator"
"""手がかりの語が読点・句点・改行を含むときの ValidationError の種類。"""

HINT_PRESET_NAME_OVERLAP_ERROR_TYPE: str = "hint_preset_name_overlap"
"""表記のヒントのプリセットの名前が重なるときの ValidationError の種類。理由の文に重なった名前を `name` として持つ。"""

ORIGIN_PATTERN: re.Pattern[str] = re.compile(r"https?://[^/\s?#]+")
"""許す Origin の形（`scheme://host[:port]`。末尾の `/` とパスは持たない）。"""

EDGE_PHRASES_FIELD_NAME: str = "edge_phrases"
"""文頭・文末から削除する文言の一覧の設定のキー。"""

EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE: str = "edge_phrase_wildcard_only"
"""文言が `*` だけのときの ValidationError の種類。設定画面がエラーの文に変える。"""

EDGE_PHRASE_WILDCARD: str = "*"
"""文頭・文末から消す文言で、0 文字以上の任意の文字列を表す文字。"""

START_HOTKEY_KEY: str = "hotkeys.start"
"""録音の開始のホットキーのキー。貼り付けて送信と同じキーにしてよい（重なりにしない）。"""

PASTE_AND_SEND_ID: str = "paste_and_send"
"""録音の開始のホットキーと同じキーにしてよい出力先の ID。"""

URL_PATTERN: str = r"^https?://"
"""プリセットの URL の形（http か https で始まる）。"""

ENDPOINT_TIMEOUT_DEFAULT_SEC: float = 1.5
"""エンドポイントへ送信するときのタイムアウトの既定（秒）。"""

ENDPOINT_TIMEOUT_MIN_SEC: float = 0.5
"""エンドポイントへ送信するときのタイムアウトの下限（秒）。"""

ENDPOINT_TIMEOUT_MAX_SEC: float = 10
"""エンドポイントへ送信するときのタイムアウトの上限（秒）。"""

AI_CHAT_ID: str = "ai_chat"
"""前の版の AI チャットの出力先の ID。読み込むときにカスタムプリセットへ読み替える。"""

DEFAULT_AI_CHAT_TARGETS: tuple[dict[str, str], ...] = (
    {"name": "ChatGPT", "url": "https://chatgpt.com", "hotkey": "<ctrl>+<alt>+1"},
    {"name": "Google AI", "url": "https://gemini.google.com/app", "hotkey": "<ctrl>+<alt>+2"},
    {"name": "Claude", "url": "https://claude.ai/new", "hotkey": "<ctrl>+<alt>+3"},
)
"""前の版の AI チャットの既定の送り先（targets が無いときの読み替えの元）。"""

type _Location = tuple[int | str, ...]


def _item(default: Any, description: str, *, reload: str, **constraints: Any) -> Any:
    """説明・再起動が要るかの印・範囲を持つ設定の項目を作る。"""
    return Field(
        default,
        description=description,
        json_schema_extra={"reload": reload},
        **constraints,
    )


def _group(factory: Any, description: str) -> Any:
    """入れ子の設定のまとまりの項目を作る（既定は中の項目の既定値）。"""
    return Field(default_factory=factory, description=description)


class _SettingsModel(BaseModel):
    """知らないキー（書き間違い）を断る設定のモデルの共通の親。"""

    model_config = ConfigDict(extra="forbid")


# === 文字起こし ===


class LocalWhisperSettings(_SettingsModel):
    """ローカルの Whisper の設定。"""

    model: str = _item("large-v3", "faster-whisper のモデル", reload=RELOAD_RESTART)
    device: Literal["cuda", "cpu"] = _item("cuda", "動かすデバイス", reload=RELOAD_RESTART)
    compute_type: Literal["float16", "int8", "float32"] = _item(
        "float16", "計算の精度", reload=RELOAD_RESTART
    )
    cpu_threads: int = _item(0, "CPU のスレッド数（0 は自動）", reload=RELOAD_RESTART, ge=0)
    num_workers: int = _item(1, "並列のデコードの数", reload=RELOAD_RESTART, ge=1)
    beam_size: int = _item(10, "ビームサーチの幅", reload=RELOAD_RESTART, ge=1)
    best_of: int = _item(5, "サンプリングの候補の数", reload=RELOAD_RESTART, ge=1)
    language: str = _item("ja", "認識する言語", reload=RELOAD_RESTART)
    vad_filter: bool = _item(True, "無音の区間を除くか", reload=RELOAD_RESTART)
    vad_threshold: float = _item(
        0.5, "音声とみなす確信度の閾値", reload=RELOAD_RESTART, ge=0, le=1
    )
    vad_min_speech_ms: int = _item(
        250, "これより短い音を雑音として除く（ミリ秒）", reload=RELOAD_RESTART, ge=0
    )
    vad_min_silence_ms: int = _item(
        2000, "これ以上の無音で区間を区切る（ミリ秒）", reload=RELOAD_RESTART, ge=0
    )
    condition_on_previous_text: bool = _item(
        False, "前の区間の文字を次の区間の文脈に使うか", reload=RELOAD_RESTART
    )
    temperature: float = _item(0.0, "サンプリングの温度", reload=RELOAD_RESTART, ge=0)
    no_speech_threshold: float = _item(
        0.6, "区間を無音とみなす確信度の閾値", reload=RELOAD_RESTART, ge=0, le=1
    )


class TranscriptionSettings(_SettingsModel):
    """使うエンジンと、エンジンごとの設定。"""

    engine: Literal["local_whisper"] = _item(
        "local_whisper", "使う文字起こしのエンジン", reload=RELOAD_RESTART
    )
    local_whisper: LocalWhisperSettings = _group(LocalWhisperSettings, "ローカルの Whisper の設定")


# === 録音・ホットキー・キーボード ===


class RecordingSettings(_SettingsModel):
    """録音中のシステム音量と、画面を出さない設定。"""

    lower_volume: bool = _item(True, "録音中にシステム音量を下げるか", reload=RELOAD_IMMEDIATE)
    volume_percent: float = _item(
        50,
        "録音中の音量の、録音前の音量に対する割合（0〜100）",
        reload=RELOAD_IMMEDIATE,
        ge=0,
        le=100,
    )
    fade_sec: float = _item(
        0.5, "音量を下げる・戻すときにかける秒数", reload=RELOAD_IMMEDIATE, ge=0
    )
    hide_window: bool = _item(
        False,
        "録音の画面も文字起こし中の表示も表示せず、トレイとホットキーだけで操作するか",
        reload=RELOAD_IMMEDIATE,
    )


class HotkeySettings(_SettingsModel):
    """録音の開始・一時停止・取り消しのホットキー（pynput の GlobalHotKeys の書式）。"""

    start: str = _item("<ctrl>+<alt>+d", "録音開始", reload=RELOAD_IMMEDIATE)
    pause: str = _item("<ctrl>+<alt>+z", "録音の一時停止・再開", reload=RELOAD_IMMEDIATE)
    cancel: str = _item("<ctrl>+<alt>+q", "録音の取り消し", reload=RELOAD_IMMEDIATE)


class KeyboardSettings(_SettingsModel):
    """貼り付け先へ送る貼り付けのキー。"""

    paste_key: str = _item(
        "<ctrl>+v", "貼り付けのキーの組み合わせ（pynput の書式）", reload=RELOAD_IMMEDIATE
    )


# === 出力先 ===


class OutputSettingsBase(_SettingsModel):
    """出力先ごとの設定のモデルが継ぐ、どの出力先も持つ ID・オン・オフ・確定のホットキー。"""

    id: str = _item(..., "出力先の ID（設定の outputs[] の判別子）", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    hotkey: str = _item(..., "この出力先で確定するホットキー", reload=RELOAD_IMMEDIATE)


# === カスタムプリセット ===


class _PresetModel(_SettingsModel):
    """セッションが確定したときの写しとして持つため、変えられないカスタムプリセットの共通の親。"""

    model_config = ConfigDict(frozen=True)


class BrowserPreset(_PresetModel):
    """ブラウザ添付の種類のプリセット 1 件。"""

    kind: Literal["browser"] = _item(
        "browser", "プリセットの種類（Preset の判別子）", reload=RELOAD_IMMEDIATE
    )
    title: str = _item(
        ..., "録音の画面のボタンに出す名前（1 文字以上）", reload=RELOAD_IMMEDIATE, min_length=1
    )
    url: str = _item(
        ...,
        "Microsoft Edge の `--app` で開く URL（http か https）",
        reload=RELOAD_IMMEDIATE,
        pattern=URL_PATTERN,
    )
    hotkey: str = _item(
        "", "このプリセットで確定するホットキー。空なら登録しない", reload=RELOAD_IMMEDIATE
    )
    enabled: bool = _item(
        True, "録音の画面にボタンを出し、ホットキーを登録するか", reload=RELOAD_IMMEDIATE
    )
    send_enter: bool = _item(
        True, "貼り付けた後に Enter まで送信するか", reload=RELOAD_IMMEDIATE
    )


class EndpointPreset(_PresetModel):
    """エンドポイントへ送信の種類のプリセット 1 件。"""

    kind: Literal["endpoint"] = _item(
        "endpoint", "プリセットの種類（Preset の判別子）", reload=RELOAD_IMMEDIATE
    )
    title: str = _item(
        ..., "録音の画面のボタンに出す名前（1 文字以上）", reload=RELOAD_IMMEDIATE, min_length=1
    )
    url: str = _item(
        ...,
        "起こした文字を POST する送信先（http か https）",
        reload=RELOAD_IMMEDIATE,
        pattern=URL_PATTERN,
    )
    hotkey: str = _item(
        "", "このプリセットで確定するホットキー。空なら登録しない", reload=RELOAD_IMMEDIATE
    )
    enabled: bool = _item(
        True, "録音の画面にボタンを出し、ホットキーを登録するか", reload=RELOAD_IMMEDIATE
    )
    # repr に出さない: 設定やセッションを repr でログに出しても値が出ないようにする
    authorization: str = _item(
        "",
        "空でなければ Authorization ヘッダーにそのまま入れる値（秘密）",
        reload=RELOAD_IMMEDIATE,
        repr=False,
    )


Preset = Annotated[BrowserPreset | EndpointPreset, Field(discriminator="kind")]
"""カスタムプリセットの種類ごとの設定の判別共用体（`kind` で見分ける）。"""


class BrowserPresetOptions(_SettingsModel):
    """ブラウザ添付の全てのプリセットで使う、開いてから貼り付けるまでの間。"""

    open_delay_sec: float = _item(
        3.0, "画面を開いてから貼り付けるまで待つ秒数", reload=RELOAD_IMMEDIATE, ge=0
    )


class EndpointPresetOptions(_SettingsModel):
    """エンドポイントへ送信の全てのプリセットで使う、送信のタイムアウト。"""

    timeout_sec: float = _item(
        ENDPOINT_TIMEOUT_DEFAULT_SEC,
        "送信のタイムアウトの秒数",
        reload=RELOAD_IMMEDIATE,
        ge=ENDPOINT_TIMEOUT_MIN_SEC,
        le=ENDPOINT_TIMEOUT_MAX_SEC,
    )


class PresetOptions(_SettingsModel):
    """プリセットの種類ごとに、その種類の全てのプリセットで使う設定。"""

    browser: BrowserPresetOptions = _group(BrowserPresetOptions, "ブラウザ添付のオプション")
    endpoint: EndpointPresetOptions = _group(
        EndpointPresetOptions, "エンドポイントへ送信のオプション"
    )


# === 履歴・ログ・画面・API ===


class HistorySettings(_SettingsModel):
    """履歴を残すかと保持期間。"""

    enabled: bool = _item(True, "録音と起こした文字を履歴に残すか", reload=RELOAD_RESTART)
    retention_days: int = _item(1, "保持する日数（1 以上）", reload=RELOAD_RESTART, ge=1)


class LoggingSettings(_SettingsModel):
    """ログのレベルと保持期間。"""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = _item(
        "INFO", "ログのレベル", reload=RELOAD_RESTART
    )
    retention_days: int = _item(
        7, "日付ごとのログを保持する日数（1 以上）", reload=RELOAD_RESTART, ge=1
    )


THEME_LABELS: dict[str, str] = {
    "system": "Windows の設定に従う",
    "light": "ライト",
    "dark": "ダーク",
}
"""画面の明暗の値 → 設定画面のラジオボタンの名前。"""


class UiSettings(_SettingsModel):
    """画面の明暗と、録音の画面・文字起こし中の表示の出し方。"""

    theme: Literal["system", "light", "dark"] = Field(
        "system",
        description="画面の明暗。system は Windows の明暗に従う",
        json_schema_extra={"reload": RELOAD_IMMEDIATE, "choice_labels": THEME_LABELS},
    )
    topmost: bool = _item(True, "常に最前面に表示するか", reload=RELOAD_IMMEDIATE)
    position: Literal["center", "top-left", "top-right", "bottom-left", "bottom-right"] = _item(
        "center", "表示する位置", reload=RELOAD_IMMEDIATE
    )
    follow_cursor: bool = _item(
        True, "マウスカーソルのあるモニターに表示するか", reload=RELOAD_IMMEDIATE
    )
    wave_gain: float = _item(
        4, "波形の振れの大きさ（0 より大きい）", reload=RELOAD_IMMEDIATE, gt=0
    )
    show_hotkeys: bool = _item(
        True, "録音の画面のボタンにホットキーを表示するか", reload=RELOAD_IMMEDIATE
    )
    transcribing_show_hotkeys: bool = _item(
        True, "文字起こし中の表示のボタンにホットキーを表示するか", reload=RELOAD_IMMEDIATE
    )

    @model_validator(mode="before")
    @classmethod
    def _inherit_transcribing_show_hotkeys(cls, data: Any) -> Any:
        """transcribing_show_hotkeys を持たない画面の設定へ、show_hotkeys の値を入れる。"""
        # dict でない・文字起こし中の表示の項目がある・録音の画面の項目が無い: そのまま返す（どちらも無ければ既定に任せる）
        if (
            not isinstance(data, dict)
            or "transcribing_show_hotkeys" in data
            or "show_hotkeys" not in data
        ):
            return data
        # 項目が無い: 録音の画面の値を入れた写しを返す（data は書き換えない）
        return {**data, "transcribing_show_hotkeys": data["show_hotkeys"]}


class ContinuousSettings(_SettingsModel):
    """API で始めた連続録音の、区切りの無音の長さとセッションの上限時間。"""

    min_silence_sec: float = _item(
        2.0,
        "連続録音を区切る無音の長さ（0.5〜10 秒）。話し声の後にこの秒数以上無音が続いたところで区間を区切る",
        reload=RELOAD_RESTART,
        ge=0.5,
        le=10,
    )
    session_limit_sec: int = _item(
        14400,
        "連続録音のセッションの上限時間（60〜86400 秒）。完了が来ないまま開始からこの秒数が経ったところで打ち切る",
        reload=RELOAD_RESTART,
        ge=60,
        le=86400,
    )


class ApiSettings(_SettingsModel):
    """API の待ち受けのポートと、返送を許すホスト、連続録音の設定。"""

    port: int = _item(
        47823,
        "127.0.0.1 で待ち受けるポート（1024〜65535）",
        reload=RELOAD_RESTART,
        ge=1024,
        le=65535,
    )
    allowed_callback_hosts: list[str] = Field(
        default_factory=list,
        description="loopback のほかに返送を許すホスト",
        json_schema_extra={"reload": RELOAD_RESTART},
    )
    continuous: ContinuousSettings = _group(
        ContinuousSettings, "連続録音の区切りと上限時間"
    )
    allowed_web_origins: list[str] = Field(
        default_factory=list,
        description=(
            "外の端末に許す Origin。`/web/` の下へ要求を送ってよいブラウザのオリジン"
            "（`https://{ゲートウェイの公開のサブドメイン}` の形。1 行に 1 つ）"
        ),
        json_schema_extra={"reload": RELOAD_RESTART},
    )

    @field_validator("allowed_web_origins")
    @classmethod
    def _origins_must_be_origin_form(cls, origins: list[str]) -> list[str]:
        """許す Origin が `scheme://host[:port]` の形（末尾の `/` とパスが無い）であることを確かめる。"""
        invalid = [origin for origin in origins if not ORIGIN_PATTERN.fullmatch(origin)]
        # 形の合わない Origin があれば断る
        if invalid:
            raise ValueError(
                f"`scheme://host[:port]` の形で、末尾の `/` とパスを付けない（{', '.join(invalid)}）"
            )
        return origins


class GlossarySettings(_SettingsModel):
    """用語集 1 つの名前と CSV の場所。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        description="用語集の名前（設定画面の一覧に出す。前後の空白を除いて 1 文字以上。ほかの用語集と重ならない）",
    )
    path: Path = Field(
        description="その用語集の CSV の場所（settings.toml のフォルダからの相対パスか絶対パス）"
    )


class GlossaryPresetSettings(_SettingsModel):
    """用語集のプリセット 1 つの名前と、補正に使う用語集の名前の並び。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        description="設定画面の用語集のプリセットの一覧と `POST /sessions` の `glossary_preset` で指す名前（前後の空白を除いて 1 文字以上。ほかのプリセットと重ならない。空は Settings の確かめが、重なりと同じ回で断る）",
    )
    glossaries: list[str] = Field(
        default_factory=list,
        description="補正に使う用語集の名前（`glossaries[].name`）の並び。補正はこの順に当てる。同じ名前を 2 回並べない。一覧に無い名前は検証では断らず、補正が外す",
    )

    @field_validator("glossaries")
    @classmethod
    def _reject_duplicated_glossaries(cls, names: list[str]) -> list[str]:
        """同じ用語集の名前を 2 回並べたプリセットを断る。"""
        duplicated = sorted({name for name in names if names.count(name) > 1})
        # 重なる名前があれば断る
        if duplicated:
            raise ValueError(f"同じ用語集を 2 回並べられない（{', '.join(duplicated)}）")
        return names


def _check_hint_word(word: str) -> str:
    """手がかりの語が空でなく、読点・句点・改行を含まないことを確かめる（前後の空白は除かれている）。"""
    # 空の語は断る
    if not word:
        raise PydanticCustomError(HINT_WORD_EMPTY_ERROR_TYPE, "語が空")
    # 区切りになる文字を含む語は断る
    if any(char in word for char in HINT_WORD_FORBIDDEN_CHARS):
        raise PydanticCustomError(HINT_WORD_SEPARATOR_ERROR_TYPE, "語に読点・句点・改行を含められない")
    return word


type HintWord = Annotated[str, AfterValidator(_check_hint_word)]
"""手がかりの語 1 つ。前後の空白を除いたうえで _check_hint_word で確かめる。"""


class HintPresetSettings(_SettingsModel):
    """表記のヒントのプリセット 1 つの名前・語の並び・有効か。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        description="設定画面の一覧に出す名前（前後の空白を除いて 1 文字以上。ほかのプリセットと重ならない）",
    )
    words: list[HintWord] = Field(
        default_factory=list,
        description="文字起こしに渡す語の並び（各語の前後の空白を除く。空の語・読点・句点・改行を含む語は断る。無効のプリセットの語も確かめる）",
    )
    enabled: bool = Field(True, description="このプリセットの語を文字起こしに渡すか")


class HintWordSource(Protocol):
    """join_hint_words が読む、有効かと語の並びだけを持つ型。確かめを通らない入力の途中の値も満たす。"""

    @property
    def enabled(self) -> bool:
        """語をつなぐか。"""
        ...

    @property
    def words(self) -> Sequence[str]:
        """語の並び。"""
        ...


class EdgePhraseSettings(_SettingsModel):
    """文頭・文末から消す文言 1 行の文言と当てる位置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(
        description="削除する文言（前後の空白を除く。`*` は 0 文字以上の任意の文字列。`*` だけは断る。空の行は Settings が一覧から除く）"
    )
    position: Literal["start", "end", "both"] = Field(
        "end", description="文言を当てる位置（start は文頭、end は文末、both は両方）"
    )

    @field_validator("text")
    @classmethod
    def _reject_wildcard_only(cls, text: str) -> str:
        """`*` だけの文言（行を丸ごと消す）を断る。空の文言はここでは断らない。"""
        # `*` だけで書かれた文言は、文頭・文末の行を丸ごと消すため断る
        if text and not text.strip(EDGE_PHRASE_WILDCARD):
            raise PydanticCustomError(
                EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE, "文言が * だけで、行を丸ごと削除してしまう"
            )
        return text


DEFAULT_EDGE_PHRASES: tuple[EdgePhraseSettings, ...] = (
    EdgePhraseSettings(text="チャンネル登録*", position="end"),
    EdgePhraseSettings(text="ご視聴ありがとうございました", position="end"),
    EdgePhraseSettings(text="ありがとうございました", position="end"),
)
"""`edge_phrases` のキーが無いときに使う既定の一覧（文末）。"""


class Settings(_SettingsModel):
    """settings.toml の全体。項目ごとに範囲・説明・再起動が要るかの印を持つ。"""

    transcription: TranscriptionSettings = _group(
        TranscriptionSettings, "使うエンジンと、エンジンごとの設定"
    )
    recording: RecordingSettings = _group(RecordingSettings, "録音中の音量・画面を出さない設定")
    hotkeys: HotkeySettings = _group(
        HotkeySettings, "録音の開始・一時停止・取り消しのホットキー"
    )
    keyboard: KeyboardSettings = _group(KeyboardSettings, "貼り付けのキー")
    outputs: list[SerializeAsAny[OutputSettingsBase]] = Field(
        default_factory=list,
        description="出力先ごとのオン・オフ・確定のホットキー・出力先ごとの設定。ID は重ならない",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    history: HistorySettings = _group(HistorySettings, "履歴を残すか・保持期間")
    logging: LoggingSettings = _group(LoggingSettings, "ログのレベル・保持期間")
    ui: UiSettings = _group(UiSettings, "録音の画面の出し方")
    glossary_path: Path | None = _item(
        None,
        "今までの用語集の CSV。glossaries が空のときだけ使う。None は設定ファイルと同じフォルダの yogo.csv",
        reload=RELOAD_IMMEDIATE,
    )
    glossaries: list[GlossarySettings] = Field(
        default_factory=list,
        description="用語集の一覧。並びが設定画面の一覧の並びになる。空のときは glossary_path の CSV を 1 つ目の用語集として扱う",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    active_glossary: str | None = _item(
        None,
        "補正に使う用語集の名前。glossary_presets が空のときだけ、「既定」のプリセットの用語集を決めるのに読む（非推奨。設定画面で保存すると削除する）",
        reload=RELOAD_IMMEDIATE,
    )
    glossary_presets: list[GlossaryPresetSettings] = Field(
        default_factory=list,
        description="用語集のプリセットの一覧。並びが設定画面の一覧の並びになる。空なら「既定」の 1 件として読む",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    active_glossary_preset: str | None = _item(
        None,
        "補正に使う用語集のプリセットの名前。None か一覧に無い名前のときは 1 件目のプリセットを使う",
        reload=RELOAD_IMMEDIATE,
    )
    hint_presets: list[HintPresetSettings] = Field(
        default_factory=list,
        description="表記のヒント（文字起こしの手がかり）のプリセットの一覧。並びが設定画面の一覧と語をつなぐ順になる。有効な語をつないだ長さが HINT_MAX_BYTES を超える設定は断る",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    edge_phrases: list[EdgePhraseSettings] = Field(
        default_factory=lambda: list(DEFAULT_EDGE_PHRASES),
        description="起こした文字の文頭・文末から削除する文言の一覧。並びが当てる順と設定画面の一覧の並びになる。キーが無いときは既定の一覧、空の一覧なら何も削除しない。文言が空の行は一覧から除く",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    api: ApiSettings = _group(ApiSettings, "待ち受けのポート・返送を許すホスト")
    presets: list[Preset] = Field(
        default_factory=list,
        description="カスタムプリセットの一覧。種類ごとの並びが、設定画面のタブと録音の画面のボタンの並びになる",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    preset_options: PresetOptions = _group(PresetOptions, "プリセットの種類ごとのオプション")

    output_models: ClassVar[Mapping[str, type[OutputSettingsBase]]] = {}
    """出力先の ID → 設定のモデル。build_settings_model が組み立てたモデルに入る。"""

    @field_validator(EDGE_PHRASES_FIELD_NAME)
    @classmethod
    def _drop_blank_edge_phrases(
        cls, phrases: list[EdgePhraseSettings]
    ) -> list[EdgePhraseSettings]:
        """文言が空の行を一覧から除く（各行の確かめを通った後のため、失敗の場所の番号は除く前の並びのまま）。"""
        return [phrase for phrase in phrases if phrase.text]

    @field_validator(OUTPUTS_FIELD_NAME)
    @classmethod
    def _output_ids_must_be_unique(
        cls, outputs: list[OutputSettingsBase]
    ) -> list[OutputSettingsBase]:
        """出力先の ID が一覧の中で重ならないことを確かめる。"""
        ids = [output.id for output in outputs]
        duplicated = sorted({output_id for output_id in ids if ids.count(output_id) > 1})
        # 重なる ID があれば断る
        if duplicated:
            raise ValueError(f"出力先の ID が重なる（{', '.join(duplicated)}）")
        return outputs

    @model_validator(mode="after")
    def _names_and_hotkeys_must_not_overlap(self) -> Settings:
        """受け付けるホットキーと用語集の名前が重ならないことを確かめる（重なったものごとに欄のエラーにし、1 回の ValidationError にまとめる）。"""
        # 重なったホットキーは、重なったキーの場所で、先のキーを理由にする
        line_errors: list[InitErrorDetails] = [
            {
                "type": PydanticCustomError(
                    HOTKEY_OVERLAP_ERROR_TYPE,
                    "{other}と同じホットキー",
                    {"other": format_error_location(first_location)},
                ),
                "loc": location,
                "input": None,
            }
            for location, first_location in _find_hotkey_overlap_locations(self)
        ]
        # 重なった用語集の名前は、後ろにある側の名前の場所で、重なった名前を添える
        line_errors += [
            {
                "type": PydanticCustomError(
                    GLOSSARY_NAME_OVERLAP_ERROR_TYPE,
                    "用語集「{name}」と同じ名前",
                    {"name": name},
                ),
                "loc": location,
                "input": name,
            }
            for location, name in _find_glossary_name_overlap_locations(self)
        ]
        # 名前が空の用語集のプリセットは、名前の場所で断る（重なりと同じ回に、欄ごとのエラーとして出すため、欄の確かめでなくここで断る）
        line_errors += [
            {
                "type": PydanticCustomError("string_too_short", "名前が空"),
                "loc": (GLOSSARY_PRESETS_FIELD_NAME, index, "name"),
                "input": preset.name,
            }
            for index, preset in enumerate(self.glossary_presets)
            if not preset.name
        ]
        # 重なった用語集のプリセットの名前は、後ろにある側の名前の場所で、重なった名前を添える
        line_errors += [
            {
                "type": PydanticCustomError(
                    GLOSSARY_PRESET_NAME_OVERLAP_ERROR_TYPE,
                    "用語集のプリセット「{name}」と同じ名前",
                    {"name": name},
                ),
                "loc": location,
                "input": name,
            }
            for location, name in _find_glossary_preset_name_overlap_locations(self)
        ]
        # 重なった表記のヒントのプリセットの名前は、後ろにある側の名前の場所で、重なった名前を添える
        line_errors += [
            {
                "type": PydanticCustomError(
                    HINT_PRESET_NAME_OVERLAP_ERROR_TYPE,
                    "表記のヒントのプリセット「{name}」と同じ名前",
                    {"name": name},
                ),
                "loc": location,
                "input": name,
            }
            for location, name in _find_hint_preset_name_overlap_locations(self)
        ]
        # 有効な語をつないだ長さが上限を超えたら、一覧の場所で、今のバイト数を添える
        hint_length = len(join_hint_words(self.hint_presets).encode("utf-8"))
        if hint_length > HINT_MAX_BYTES:
            line_errors.append(
                {
                    "type": PydanticCustomError(
                        HINT_TOO_LONG_ERROR_TYPE,
                        "有効なヒントが長すぎる（{length} バイト）",
                        {"length": hint_length},
                    ),
                    "loc": (HINT_PRESETS_FIELD_NAME,),
                    "input": None,
                }
            )
        # 重なりや超過があれば断る
        if line_errors:
            raise ValidationError.from_exception_data(type(self).__name__, line_errors)
        return self


# === 設定のモデルの組み立て ===


def build_settings_model(output_models: Sequence[type[OutputSettingsBase]]) -> type[Settings]:
    """出力先の設定のモデルを受け、outputs をその判別共用体と既定の一覧にした Settings の子のモデルを返す。"""
    # 1. 各モデルの id の既定値を集める（空か重なるなら登録の誤りなので断る）
    ids = [model.model_fields["id"].default for model in output_models]
    duplicated = sorted({output_id for output_id in ids if ids.count(output_id) > 1})
    if not ids:
        raise ValueError("出力先の設定のモデルが 1 つも無い")
    if duplicated:
        raise ValueError(f"出力先の設定のモデルの ID が重なる（{', '.join(duplicated)}）")

    # 2. outputs の型を判別共用体にする（モデルが 1 つでも判別共用体にし、失敗の場所に添字の次の判別子の値を入れる）
    union = reduce(operator.or_, output_models)
    outputs_type = list[Annotated[union, Field(discriminator="id")]]

    # 3. outputs の既定を、各モデルを引数なしで作った一覧にする（説明・反映の印は Settings のものを引き継ぐ）
    base_field = Settings.model_fields[OUTPUTS_FIELD_NAME]
    outputs_field = Field(
        default_factory=lambda: [model() for model in output_models],
        description=base_field.description,
        json_schema_extra=base_field.json_schema_extra,
    )

    # 4. Settings を継いだモデルを作り、ID → モデルを入れる
    settings_model = create_model(
        "AppSettings", __base__=Settings, outputs=(outputs_type, outputs_field)
    )
    settings_model.output_models = dict(zip(ids, output_models, strict=True))
    return settings_model


# === ホットキーの重なり ===


def _accepted_hotkeys(settings: Settings) -> list[tuple[_Location, str, bool]]:
    """受け付けるホットキーを（場所, 小文字の値, 貼り付けて送信のホットキーか）で、重なりを見る順に並べる。"""
    accepted: list[tuple[_Location, str, bool]] = [
        (("hotkeys", "start"), settings.hotkeys.start.lower(), False),
        (("hotkeys", "pause"), settings.hotkeys.pause.lower(), False),
        (("hotkeys", "cancel"), settings.hotkeys.cancel.lower(), False),
    ]
    # オンの出力先のホットキー（出力先の判別子の値が場所の 3 つ目に入る）
    for index, output in enumerate(settings.outputs):
        if output.enabled:
            location = (OUTPUTS_FIELD_NAME, index, output.id, "hotkey")
            accepted.append((location, output.hotkey.lower(), output.id == PASTE_AND_SEND_ID))
    # 有効なプリセットのホットキー（種類をまたいで 1 つの並び。判別子の値が場所の 3 つ目に入る）
    for index, preset in enumerate(settings.presets):
        if preset.enabled:
            location = (PRESETS_FIELD_NAME, index, preset.kind, "hotkey")
            accepted.append((location, preset.hotkey.lower(), False))
    # 空のホットキーは受け付けないので、重なりを見ない
    return [item for item in accepted if item[1]]


def _find_hotkey_overlap_locations(settings: Settings) -> list[tuple[_Location, _Location]]:
    """前に並んだものと重なるホットキーの（場所, 先に並んだ同じホットキーの場所）を返す。"""
    first_location_by_value: dict[str, _Location] = {}
    overlaps: list[tuple[_Location, _Location]] = []
    for location, value, is_paste_and_send in _accepted_hotkeys(settings):
        first_location = first_location_by_value.get(value)
        # 初めてのホットキーは控える
        if first_location is None:
            first_location_by_value[value] = location
        # 録音の開始と貼り付けて送信が同じキーなのは、録音中に押すとその出力先で確定する既定なので重なりにしない
        elif is_paste_and_send and format_error_location(first_location) == START_HOTKEY_KEY:
            continue
        else:
            overlaps.append((location, first_location))
    return overlaps


def find_hotkey_overlaps(settings: Settings) -> list[tuple[str, str]]:
    """前に並んだホットキーと重なるキーを（重なったキー, 先に並んだ同じホットキーのキー）で返す。"""
    return [
        (format_error_location(location), format_error_location(first_location))
        for location, first_location in _find_hotkey_overlap_locations(settings)
    ]


# === 用語集の名前の重なり ===


def _find_glossary_name_overlap_locations(settings: Settings) -> list[tuple[_Location, str]]:
    """前に並んだ用語集と名前が同じ用語集の（名前の場所, 名前）を返す。大文字と小文字は区別する。"""
    seen: set[str] = set()
    overlaps: list[tuple[_Location, str]] = []
    for index, glossary in enumerate(settings.glossaries):
        # 初めての名前は控え、先に並んだ名前と同じなら重なりとして集める
        if glossary.name in seen:
            overlaps.append(((GLOSSARIES_FIELD_NAME, index, "name"), glossary.name))
        else:
            seen.add(glossary.name)
    return overlaps


def find_glossary_name_overlaps(settings: Settings) -> list[tuple[str, str]]:
    """前に並んだ用語集と名前が同じものを（重なったキー, 重なった名前）で返す。"""
    return [
        (format_error_location(location), name)
        for location, name in _find_glossary_name_overlap_locations(settings)
    ]


# === 用語集のプリセットの名前の重なり ===


def _find_glossary_preset_name_overlap_locations(
    settings: Settings,
) -> list[tuple[_Location, str]]:
    """前に並んだプリセットと名前が同じ用語集のプリセットの（名前の場所, 名前）を返す。大文字と小文字は区別する。"""
    seen: set[str] = set()
    overlaps: list[tuple[_Location, str]] = []
    for index, preset in enumerate(settings.glossary_presets):
        # 初めての名前は控え、先に並んだ名前と同じなら重なりとして集める
        if preset.name in seen:
            overlaps.append(((GLOSSARY_PRESETS_FIELD_NAME, index, "name"), preset.name))
        else:
            seen.add(preset.name)
    return overlaps


def find_glossary_preset_name_overlaps(settings: Settings) -> list[tuple[str, str]]:
    """前に並んだプリセットと名前が同じ用語集のプリセットを（重なったキー, 重なった名前）で返す。"""
    return [
        (format_error_location(location), name)
        for location, name in _find_glossary_preset_name_overlap_locations(settings)
    ]


# === 表記のヒント ===


def join_hint_words(presets: Sequence[HintWordSource]) -> str:
    """有効なプリセットの語を、一覧の上から順に読点でつなぐ。有効な語が無ければ空文字を返す。"""
    words = [word for preset in presets if preset.enabled for word in preset.words]
    return HINT_SEPARATOR.join(words)


def _find_hint_preset_name_overlap_locations(settings: Settings) -> list[tuple[_Location, str]]:
    """前に並んだプリセットと名前が同じ表記のヒントのプリセットの（名前の場所, 名前）を返す。大文字と小文字は区別する。"""
    seen: set[str] = set()
    overlaps: list[tuple[_Location, str]] = []
    for index, preset in enumerate(settings.hint_presets):
        # 初めての名前は控え、先に並んだ名前と同じなら重なりとして集める
        if preset.name in seen:
            overlaps.append(((HINT_PRESETS_FIELD_NAME, index, "name"), preset.name))
        else:
            seen.add(preset.name)
    return overlaps


def find_hint_preset_name_overlaps(settings: Settings) -> list[tuple[str, str]]:
    """前に並んだプリセットと名前が同じ表記のヒントのプリセットを（重なったキー, 重なった名前）で返す。"""
    return [
        (format_error_location(location), name)
        for location, name in _find_hint_preset_name_overlap_locations(settings)
    ]


# === 検証の失敗の整形 ===


def format_error_location(location: tuple[int | str, ...]) -> str:
    """pydantic の失敗の場所をドット区切り（添字は `[0]`）のキーにする。"""
    parts = list(location)
    # 出力先・プリセットの判別共用体は、添字の次に判別子の値（paste_only・browser など）が入るので外す
    if (
        len(parts) > OUTPUT_DISCRIMINATOR_INDEX
        and parts[0] in DISCRIMINATED_LIST_FIELD_NAMES
        and isinstance(parts[1], int)
    ):
        del parts[OUTPUT_DISCRIMINATOR_INDEX]

    key = ""
    for part in parts:
        if isinstance(part, int):
            key += f"[{part}]"
        elif key:
            key += f".{part}"
        else:
            key = part
    return key


def list_validation_failures(error: ValidationError) -> list[tuple[str, str]]:
    """検証の失敗を（キー, 理由）の一覧にする。"""
    return [(format_error_location(failure["loc"]), failure["msg"]) for failure in error.errors()]


# === 古い AI チャットの設定の読み替え ===


def migrate_ai_chat(document: dict[str, Any]) -> dict[str, Any]:
    """`id = "ai_chat"` の出力先を外し、送り先をブラウザ添付のプリセットへ読み替えた dict を返す。"""
    # 1. outputs の中の ai_chat の項目を探す
    outputs = document.get(OUTPUTS_FIELD_NAME)
    # outputs が無い・配列でないときは、検証を Settings に任せる
    if not isinstance(outputs, list):
        return document
    ai_chats = [
        output for output in outputs if isinstance(output, dict) and output.get("id") == AI_CHAT_ID
    ]
    # ai_chat が無ければ変えない
    if not ai_chats:
        return document

    migrated = copy.deepcopy(document)
    presets = list(migrated.get(PRESETS_FIELD_NAME, []))
    for ai_chat in copy.deepcopy(ai_chats):
        # 2. 送り先（無ければ前の既定の 3 件）を並びのまま、ブラウザ添付のプリセットにして足す
        targets = ai_chat.get("targets")
        if targets is None:
            targets = [{**target, "enabled": True} for target in DEFAULT_AI_CHAT_TARGETS]
        output_enabled = ai_chat.get("enabled", True)
        presets.extend(
            {
                "kind": "browser",
                "title": target.get("name"),
                "url": target.get("url"),
                "hotkey": target.get("hotkey", ""),
                "enabled": bool(output_enabled and target.get("enabled", True)),
                "send_enter": True,
            }
            for target in targets
        )

        # 3. 開くまでの間を、ブラウザ添付のオプションへ移す（既にあればそちらを使う）
        if "open_delay_sec" in ai_chat:
            browser_options = migrated.setdefault("preset_options", {}).setdefault("browser", {})
            browser_options.setdefault("open_delay_sec", ai_chat["open_delay_sec"])

    # 4. ai_chat の項目を外す
    migrated[PRESETS_FIELD_NAME] = presets
    migrated[OUTPUTS_FIELD_NAME] = [
        output
        for output in outputs
        if not (isinstance(output, dict) and output.get("id") == AI_CHAT_ID)
    ]
    logger.info(f"古い AI チャットの設定をプリセットへ読み替えた（{len(presets)} 件）")
    return migrated


# === 読み込み ===


def load_settings(path: Path, model: type[Settings]) -> Settings:
    """settings.toml を読んで model で検証する。無ければ既定値で作る。"""
    # 1. 設定ファイルが無いか
    if not path.exists():
        # 無い: 既定の設定を書いて返す
        settings = model()
        save_settings(path, settings)
        logger.info(f"設定ファイルが無いため既定値で作った（{path}）")
        return settings

    # 2. UTF-8 で読み、tomlkit で解釈する
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except TOMLKitError as error:
        raise SettingsError(f"設定ファイルを読めない（{path}: {error}）") from error

    # 3. 素の dict にして検証する
    try:
        return model.model_validate(migrate_ai_chat(document.unwrap()))
    except ValidationError as error:
        failures = "、".join(f"{key}: {reason}" for key, reason in list_validation_failures(error))
        raise SettingsError(f"設定の値が合わない（{failures}）") from error


# === 書き戻し ===


def save_settings(path: Path, settings: Settings) -> bool:
    """検証した設定をコメントを保ったまま書き戻し、再起動が要る項目が変わったかを返す。"""
    # 1・2. 既にある設定ファイルを読み、前の設定にする
    document, previous, unreadable = _read_existing(path, type(settings))

    # 3. 設定を JSON の値にする（用語集の場所は、設定のフォルダの下なら相対パスにする）
    data = settings.model_dump(mode="json", exclude_none=True)
    for glossary in data.get(GLOSSARIES_FIELD_NAME, []):
        glossary_path = Path(glossary["path"])
        if glossary_path.is_relative_to(path.parent):
            glossary["path"] = glossary_path.relative_to(path.parent).as_posix()

    # 4. 文書の値を置き換える
    _merge_into(document, data)

    # 5. 同じフォルダの一時ファイルへ書いて置き換える
    _write_atomically(path, tomlkit.dumps(document))

    # 6. 再起動が要る項目が変わったか
    # 読めない・検証に通らなかった設定は、全て変わったとして扱う
    if unreadable:
        return True
    # 前の設定が無い（新しく作った）
    if previous is None:
        return False
    return _restart_item_changed(previous, settings)


def _read_existing(
    path: Path, model: type[Settings]
) -> tuple[tomlkit.TOMLDocument, Settings | None, bool]:
    """既にある settings.toml を model で検証し、（文書, 前の設定, 読めないか）にして返す。"""
    # 設定ファイルが無いか
    if not path.exists():
        return tomlkit.document(), None, False

    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
        return document, model.model_validate(migrate_ai_chat(document.unwrap())), False
    except (TOMLKitError, ValidationError):
        # 読めない・検証に通らない: 内容を空の文書にして書き直す
        return tomlkit.document(), None, True


def _unwrap(value: Any) -> Any:
    """tomlkit の値を素の Python の値にする。"""
    return value.unwrap() if hasattr(value, "unwrap") else value


def _is_table_like(value: Any) -> bool:
    """TOML では表（`[name]`・`[[name]]`）になる値か。"""
    return isinstance(value, dict) or (
        isinstance(value, list) and bool(value) and isinstance(value[0], dict)
    )


def _merge_into(target: MutableMapping[str, Any], source: dict[str, Any]) -> None:
    """source の値で target を再帰で置き換える。表はキーごとに、配列は丸ごと入れ替える。"""
    # source に無いキー（None の項目）は消す。知らないキーは検証で断られるので、残るのは None の項目だけ
    for key in [key for key in target if key not in source]:
        del target[key]

    # 後ろに表が無い配列の表のコメントと空行。全ての値を置き換えた後に target の末尾へ足す
    tail: list[Item] = []

    # 表の後に置くとその表のキーとして読まれる値を、先に並べる
    for key, value in sorted(source.items(), key=lambda entry: _is_table_like(entry[1])):
        existing = target.get(key)
        # 表: 既にある表の中を再帰で置き換える
        if isinstance(value, dict) and isinstance(existing, MutableMapping):
            _merge_into(existing, value)
        # 変わった配列の表: 後ろのコメントを付け直して入れ替える
        elif isinstance(existing, AoT) and isinstance(value, list) and _unwrap(existing) != value:
            tail.extend(_replace_array_table(target, key, value))
        # 値が変わっていなければ書式とコメントのために触らない
        elif key not in target or _unwrap(existing) != value:
            target[key] = value

    if isinstance(target, Container | Table):
        for item in tail:
            target.append(None, item)


def _replace_array_table(
    target: MutableMapping[str, Any], key: str, value: list[Any]
) -> list[Item]:
    """target の配列の表 key を value に入れ替え、古い配列の表の最初の見出しの前と後ろのコメントを付け直す。target の末尾へ足すものを返す。"""
    old = target[key]

    # 入れ替える前に、古い最初の見出しの前と、最後の要素の末尾のコメントと空行、古い配列の表の次の表を控える
    heading_indent = old.body[0].trivia.indent
    trailing = _trailing_trivia(old.body[-1])
    following = _following_heading(target, key)

    target[key] = value
    new = target[key]

    # 1 件以上: 新しい最初の見出しの前と、新しい最後の要素の末尾へ同じ並びで付け直す
    if isinstance(new, AoT):
        new.body[0].trivia.indent = heading_indent
        for item in trailing:
            new.body[-1].append(None, item)
        return []

    # 0 件で次の表がある: 次の表の見出しの前の頭へ付け直す
    moved = heading_indent + "".join(item.as_string() for item in trailing)
    if following is not None:
        following.trivia.indent = moved + following.trivia.indent
        return []

    # 0 件で次の表が無い: 文書の末尾へ足す
    return [Whitespace(heading_indent), *trailing] if heading_indent else trailing


def _trailing_trivia(table: Table) -> list[Item]:
    """表の末尾にある、キーを持たないコメントと空行を並びのまま返す。"""
    body = table.value.body
    start = len(body)
    while start > 0 and _is_trivia(body[start - 1]):
        start -= 1
    return [item for _key, item in body[start:]]


def _is_trivia(entry: tuple[Key | None, Item]) -> bool:
    """表の中身の 1 つが、キーを持たないコメントか空行か。"""
    key, item = entry
    return key is None and isinstance(item, Comment | Whitespace)


def _following_heading(target: MutableMapping[str, Any], key: str) -> Table | None:
    """target で key の配列の表の次に並ぶ表のうち、見出しを持つ最初の表を返す。無ければ None。"""
    if not isinstance(target, Container | Table):
        return None
    body = target.body if isinstance(target, Container) else target.value.body
    position = max(index for index, (name, _item) in enumerate(body) if name and name.key == key)
    for _name, item in body[position + 1 :]:
        heading = _first_heading(item)
        if heading is not None:
            return heading
    return None


def _first_heading(item: Item) -> Table | None:
    """item の中で最初に見出しを書く表を返す。super table（見出しを持たない表）は中の最初の表を探す。"""
    if isinstance(item, AoT):
        return item.body[0]
    if not isinstance(item, Table):
        return None
    children = [child for _key, child in item.value.body]
    # 見出しを書く表: super table でない、または表以外の値を持つ
    if not item.is_super_table() or any(
        not isinstance(child, Table | AoT | Whitespace | Null) for child in children
    ):
        return item
    # 見出しを書かない表: 中の最初の見出しを探す
    for child in children:
        heading = _first_heading(child)
        if heading is not None:
            return heading
    return None


def _write_atomically(path: Path, text: str) -> None:
    """親のフォルダを作り、同じフォルダの一時ファイルへ UTF-8 で書いて os.replace で置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(text)
        temp_path = Path(temp_file.name)
    try:
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _restart_item_changed(previous: BaseModel, current: BaseModel) -> bool:
    """再起動が要る印の項目のうち、値が違うものがあるか。"""
    for name, field in type(current).model_fields.items():
        before = getattr(previous, name)
        after = getattr(current, name)
        # 入れ子のまとまり: 中の項目を見る
        if isinstance(after, BaseModel):
            if _restart_item_changed(before, after):
                return True
            continue
        extra = field.json_schema_extra
        reload = extra.get("reload") if isinstance(extra, dict) else None
        # 再起動が要る印の項目の値が変わったか
        if reload == RELOAD_RESTART and before != after:
            return True
    return False
