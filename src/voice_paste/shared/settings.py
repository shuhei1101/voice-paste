"""設定のモデル（pydantic）と、既定値・環境の値・checkout の上書きの 3 レイヤーの読み込みと環境の値の書き戻し、settings.toml からの移行。"""

from __future__ import annotations

import copy
import logging
import operator
import re
from collections.abc import Mapping, Sequence
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, NamedTuple, Protocol

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
from tomlkit.exceptions import TOMLKitError

from voice_paste.shared.errors import SettingsError
from voice_paste.shared.os_kind import CURRENT_OS, OsKind
from voice_paste.shared.yaml_document import (
    changed_keys,
    delete_key,
    diff_from_defaults,
    merge_layers,
    read_yaml_document,
    read_yaml_mapping,
    set_key,
    write_yaml_document,
)

if TYPE_CHECKING:
    from voice_paste.shared.constants import AppPaths

logger = logging.getLogger(__name__)

RELOAD_IMMEDIATE: str = "immediate"
"""設定画面で保存すると、動いている常駐アプリに効く項目のマーカー。"""

RELOAD_RESTART: str = "restart"
"""再起動してから効く項目のマーカー。"""

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

faster-whisper が hotwords を先頭の 223 トークンに切ることから、頭に追加する空白の 1 バイトを引いた値。
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

HINT_READING_NOT_KANA_ERROR_TYPE: str = "hint_reading_not_kana"
"""読みにひらがな・カタカナ・長音符以外の文字が入っているときの、失敗の種類。"""

HINT_READINGS_LENGTH_ERROR_TYPE: str = "hint_readings_length"
"""読みの数が語の数と合わないときの、失敗の種類。"""

HINT_READING_CONFLICT_ERROR_TYPE: str = "hint_reading_conflict"
"""同じプリセットの同じ語に違う読みがあるときの、失敗の種類。"""

HINT_READING_PATTERN: re.Pattern[str] = re.compile(r"[ぁ-ゖゝゞァ-ヺーヽヾ]*")
"""読みに使えるひらがな・カタカナ・長音符の並び。"""

HAAS_PORT_OVERLAP_ERROR_TYPE: str = "haas_port_overlap"
"""Haas のサーバーのポートが API のポートと同じときの、失敗の種類。"""

HAAS_MODEL_EMPTY_ERROR_TYPE: str = "haas_model_empty"
"""Haas のモデルが空のときの、失敗の種類。"""

HAAS_DEVICE_FORM_ERROR_TYPE: str = "haas_device_form"
"""Haas の装置が HAAS_DEVICE_PATTERN に合わないときの、失敗の種類。"""

HAAS_SEPARATOR_TOO_LONG_ERROR_TYPE: str = "haas_separator_too_long"
"""Haas の区切りをつなぐ文字が HAAS_SEPARATOR_MAX_LENGTH 文字を超えるときの、失敗の種類。"""

HAAS_DEVICE_PATTERN: re.Pattern[str] = re.compile(r"\A(cuda(:\d+)?|cpu)\Z")
"""transcription.haas.device に許す形式（cuda・cuda:{番号}・cpu）。"""

HAAS_SEPARATOR_MAX_LENGTH: int = 16
"""transcription.haas.separator の文字数の上限（Haas のサーバーの要求の制約と同じ）。"""

HINT_PRESET_NAME_OVERLAP_ERROR_TYPE: str = "hint_preset_name_overlap"
"""表記のヒントのプリセットの名前が重なるときの ValidationError の種類。理由の文に重なった名前を `name` として持つ。"""

ORIGIN_PATTERN: re.Pattern[str] = re.compile(r"https?://[^/\s?#]+")
"""許す Origin の形式（`scheme://host[:port]`。末尾の `/` とパスは持たない）。"""

WEB_ORIGIN_FORM_ERROR_TYPE: str = "web_origin_form"
"""許す Origin に形式の違う行があるときの PydanticCustomError の種類。設定画面がエラーの文に変える。"""

EDGE_PHRASES_FIELD_NAME: str = "edge_phrases"
"""文頭・文末から削除する文言の一覧の設定のキー。"""

EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE: str = "edge_phrase_wildcard_only"
"""文言が `*` だけのときの ValidationError の種類。設定画面がエラーの文に変える。"""

EDGE_PHRASE_WILDCARD: str = "*"
"""文頭・文末から削除する文言で、0 文字以上の任意の文字列を表す文字。"""

START_HOTKEY_KEY: str = "hotkeys.start"
"""録音の開始のホットキーのキー。貼り付けて送信と同じキーにしてよい（重なりにしない）。"""

PASTE_AND_SEND_ID: str = "paste_and_send"
"""録音の開始のホットキーと同じキーにしてよい出力先の ID。"""

URL_PATTERN: str = r"^https?://"
"""プリセットの URL の形式（http か https で始まる）。"""

ENDPOINT_TIMEOUT_MIN_SEC: float = 0.5
"""エンドポイントへ送信するときのタイムアウトの下限（秒）。"""

ENDPOINT_TIMEOUT_MAX_SEC: float = 10
"""エンドポイントへ送信するときのタイムアウトの上限（秒）。"""

AI_CHAT_ID: str = "ai_chat"
"""前のバージョンの AI チャットの出力先の ID。読み込むときにカスタムプリセットへ読み替える。"""

DEFAULT_AI_CHAT_TARGETS: tuple[dict[str, str], ...] = (
    {"name": "ChatGPT", "url": "https://chatgpt.com", "hotkey": "<ctrl>+<alt>+1"},
    {"name": "Google AI", "url": "https://gemini.google.com/app", "hotkey": "<ctrl>+<alt>+2"},
    {"name": "Claude", "url": "https://claude.ai/new", "hotkey": "<ctrl>+<alt>+3"},
)
"""前のバージョンの AI チャットの既定の送信先（targets が無いときの読み替えの元）。"""

DEFAULTS_OS_OVERRIDES_KEY: str = "os_overrides"
"""config/defaults.yaml の中で、OS ごとの既定値の上書きを持つ一番上のキー。中は OsKind の値 → 設定と同じ構造の上書き。"""

PRESET_OPTIONS_FIELD_NAME: str = "preset_options"
"""プリセットの種類ごとのオプションを持つ Settings の項目名。"""

type _Location = tuple[int | str, ...]


def _required(description: str, *, reload: str, **constraints: Any) -> Any:
    """説明・再起動が要るかのマーカー・範囲を持つ、既定値の無い設定の項目を作る（既定値は config/defaults.yaml が持つ）。"""
    return Field(description=description, json_schema_extra={"reload": reload}, **constraints)


def _item(default: Any, description: str, *, reload: str, **constraints: Any) -> Any:
    """説明・再起動が要るかのマーカー・範囲と既定値を持つ、一覧の要素の設定の項目を作る。"""
    return Field(
        default,
        description=description,
        json_schema_extra={"reload": reload},
        **constraints,
    )


def _group(description: str) -> Any:
    """入れ子の設定のまとまりの項目を作る（既定値は持たない）。"""
    return Field(description=description)


class _SettingsModel(BaseModel):
    """知らないキー（書き間違い）を断る設定のモデルの共通の親。"""

    model_config = ConfigDict(extra="forbid")


# === 文字起こし ===


class LocalWhisperSettings(_SettingsModel):
    """ローカルの Whisper の設定。"""

    model: str = _required("faster-whisper のモデル", reload=RELOAD_RESTART)
    device: Literal["cuda", "cpu"] = _required(
        "動かすデバイス",
        reload=RELOAD_RESTART,
    )
    compute_type: Literal["float16", "int8", "float32"] = _required(
        "計算の精度",
        reload=RELOAD_RESTART,
    )
    cpu_threads: int = _required("CPU のスレッド数（0 は自動）", reload=RELOAD_RESTART, ge=0)
    num_workers: int = _required("並列のデコードの数", reload=RELOAD_RESTART, ge=1)
    beam_size: int = _required("ビームサーチの幅", reload=RELOAD_RESTART, ge=1)
    best_of: int = _required("サンプリングの候補の数", reload=RELOAD_RESTART, ge=1)
    language: str = _required("認識する言語", reload=RELOAD_RESTART)
    vad_filter: bool = _required("無音の区間を除くか", reload=RELOAD_RESTART)
    vad_threshold: float = _required("音声とみなす確信度の閾値", reload=RELOAD_RESTART, ge=0, le=1)
    vad_min_speech_ms: int = _required(
        "これより短い音を雑音として除く（ミリ秒）", reload=RELOAD_RESTART, ge=0
    )
    vad_min_silence_ms: int = _required(
        "これ以上の無音で区間を区切る（ミリ秒）", reload=RELOAD_RESTART, ge=0
    )
    condition_on_previous_text: bool = _required(
        "前の区間の文字を次の区間の文脈に使うか", reload=RELOAD_RESTART
    )
    temperature: float = _required("サンプリングの温度", reload=RELOAD_RESTART, ge=0)
    no_speech_threshold: float = _required(
        "区間を無音とみなす確信度の閾値", reload=RELOAD_RESTART, ge=0, le=1
    )


ENGINE_LABELS: dict[str, str] = {
    "local_whisper": "ローカルの Whisper",
    "openai": "OpenAI API",
    "haas": "Haas（WSL）",
}
"""文字起こしのエンジンの値 → 設定画面の選択欄の名前。"""

OPENAI_BASE_URL_DEFAULT: str = "https://api.openai.com/v1"
"""OpenAI API の送信先のベース URL の既定。"""

OPENAI_BASE_URL_KEY: str = "transcription.openai.base_url"
"""OpenAI API のベース URL の設定のキー。"""

OPENAI_NOTE: str = (
    "文字起こしのエンジンが OpenAI API のときに使う。"
    "API キーはここでは入れず、環境変数 OPENAI_API_KEY か、"
    "settings.yaml と同じフォルダの secrets/openai_api_key に置く。"
)
"""設定画面で OpenAI API の欄の下に出す補助文。"""


class OpenAISettings(_SettingsModel):
    """OpenAI API の文字起こしへ渡すモデル・言語・送信先のベース URL。API キーは持たない。"""

    model: str = Field(
        description="OpenAI のモデル",
        json_schema_extra={"reload": RELOAD_RESTART, "note": OPENAI_NOTE},
    )
    language: str = _required("OpenAI の言語（ISO-639-1）", reload=RELOAD_RESTART)
    base_url: str = _required(
        "OpenAI のベース URL",
        reload=RELOAD_RESTART,
        pattern=URL_PATTERN,
    )


HAAS_NOTE: str = (
    "文字起こしのエンジンが Haas（WSL）のときに使う。"
    "WSL2 のネットワークを mirrored にし、このディストリビューションにサーバーの環境を作っておく。"
    "空なら WSL の既定のディストリビューションを使う。"
)
"""Haas の設定のまとまりの欄の下に出す補助文。"""

HAAS_DTYPE_LABELS: dict[str, str] = {
    "auto": "自動",
    "bfloat16": "bfloat16",
    "float16": "float16",
    "float32": "float32",
}
"""Haas の計算の精度の値 → 設定画面のラジオボタンの名前。"""


def _haas_field(
    description: str, note: str | None, *, reload: str, **constraints: Any
) -> Any:
    """説明・補助文・再起動が要るかのマーカー・範囲を持つ、既定値の無い Haas の設定の項目を作る。"""
    extra: dict[str, Any] = {"reload": reload}
    if note is not None:
        extra["note"] = note
    return Field(description=description, json_schema_extra=extra, **constraints)


class HaasSettings(_SettingsModel):
    """Haas の文字起こしのサーバーを動かす WSL のディストリビューション・待ち受けのポートと、認識の調整の値。

    model・dtype・device はサーバーの起動で決まるため restart、ほかの調整の値は送信するたびに読むため immediate。
    範囲は Haas のサーバーの要求の制約と同じにする（サーバーは別のサブシステムで import できないため、値は両方に持つ）。
    """

    distribution: str = Field(
        description="WSL のディストリビューション",
        json_schema_extra={"reload": RELOAD_RESTART, "note": HAAS_NOTE},
    )
    port: int = _required("サーバーのポート", reload=RELOAD_RESTART, ge=1024, le=65535)
    model: str = _haas_field(
        "モデル",
        "Hugging Face Hub のモデルの名前か、WSL の中の .nemo ファイルのパス。",
        reload=RELOAD_RESTART,
    )
    dtype: Literal["auto", "bfloat16", "float16", "float32"] = Field(
        description="計算の精度",
        json_schema_extra={
            "reload": RELOAD_RESTART,
            "choice_labels": HAAS_DTYPE_LABELS,
            "note": "自動は GPU では bfloat16、CPU では float32。公開された精度と速さは bfloat16 で測られている。",
        },
    )
    device: str = _haas_field("装置", "cuda・cuda:{番号}・cpu のどれか。", reload=RELOAD_RESTART)
    alpha: float = _haas_field(
        "手がかりの強さ",
        "表記のヒントの単語をどれだけ強く優先するか。"
        "上げると聞き逃した単語を検出しやすくなるが、話していない単語を出力することも増える。",
        reload=RELOAD_IMMEDIATE,
        ge=0.0,
        le=10.0,
    )
    guard: bool = _haas_field(
        "手がかりの採否を確認する",
        "手がかりなしでも起こし、ヒントの単語が丸ごと入った変化だけを採用する。",
        reload=RELOAD_IMMEDIATE,
    )
    short_audio_limit_sec: float = _haas_field(
        "一度に起こす長さの上限（秒）",
        "これより長い音声は静かな箇所で区切って起こす。モデルが学習した発話は約 30 秒まで。",
        reload=RELOAD_IMMEDIATE,
        ge=1.0,
        le=60.0,
    )
    chunk_sec: float = _haas_field(
        "区切る長さ（秒）",
        "区切る位置は、この長さの前後でいちばん静かな箇所にずらす。",
        reload=RELOAD_IMMEDIATE,
        ge=1.0,
        le=60.0,
    )
    search_sec: float = _haas_field(
        "静かな箇所を探す幅（秒）", None, reload=RELOAD_IMMEDIATE, ge=0.0, le=10.0
    )
    window_sec: float = _haas_field(
        "静かさを測る窓（秒）", None, reload=RELOAD_IMMEDIATE, ge=0.01, le=1.0
    )
    separator: str = _haas_field(
        "区切りをつなぐ文字",
        "既定は空（日本語は単語の間を空けない）。",
        reload=RELOAD_IMMEDIATE,
    )
    batch_size: int = _haas_field(
        "まとめて起こす数",
        "長い音声の区切りをいくつまとめて起こすか。変えると紙一重の箇所の結果がまれに変わる。",
        reload=RELOAD_IMMEDIATE,
        ge=1,
        le=256,
    )

    @field_validator("model")
    @classmethod
    def _model_must_not_be_empty(cls, value: str) -> str:
        """前後の空白を除いて空のモデルを断る。"""
        if not value.strip():
            raise PydanticCustomError(HAAS_MODEL_EMPTY_ERROR_TYPE, "モデルが空")
        return value

    @field_validator("device")
    @classmethod
    def _device_must_match_form(cls, value: str) -> str:
        """cuda・cuda:{番号}・cpu 以外の装置を断る。"""
        if HAAS_DEVICE_PATTERN.match(value) is None:
            raise PydanticCustomError(HAAS_DEVICE_FORM_ERROR_TYPE, "装置の形式が違う")
        return value

    @field_validator("separator")
    @classmethod
    def _separator_must_be_short(cls, value: str) -> str:
        """HAAS_SEPARATOR_MAX_LENGTH 文字を超える区切りをつなぐ文字を断る。"""
        if len(value) > HAAS_SEPARATOR_MAX_LENGTH:
            raise PydanticCustomError(
                HAAS_SEPARATOR_TOO_LONG_ERROR_TYPE, "区切りをつなぐ文字が長い"
            )
        return value


class TranscriptionSettings(_SettingsModel):
    """使うエンジンと、エンジンごとの設定。"""

    engine: Literal["local_whisper", "openai", "haas"] = Field(
        description="使う文字起こしのエンジン",
        json_schema_extra={"reload": RELOAD_RESTART, "choice_labels": ENGINE_LABELS},
    )
    local_whisper: LocalWhisperSettings = _group("ローカルの Whisper の設定")
    openai: OpenAISettings = _group("OpenAI API の設定")
    haas: HaasSettings = _group("Haas の文字起こしのサーバーの設定")


# === 録音・ホットキー・キーボード ===


class RecordingSettings(_SettingsModel):
    """録音中のシステム音量と、画面を出さない設定。"""

    lower_volume: bool = _required(
        "録音中にシステム音量を下げるか",
        reload=RELOAD_IMMEDIATE,
    )
    volume_percent: float = _required(
        "録音中の音量の、録音前の音量に対する割合（0〜100）",
        reload=RELOAD_IMMEDIATE,
        ge=0,
        le=100,
    )
    fade_sec: float = _required("音量を下げる・戻すときにかける秒数", reload=RELOAD_IMMEDIATE, ge=0)
    hide_window: bool = _required(
        "録音の画面も文字起こし中の表示も表示せず、トレイとホットキーだけで操作するか",
        reload=RELOAD_IMMEDIATE,
    )


class HotkeySettings(_SettingsModel):
    """録音の開始・一時停止・取り消しのホットキー（pynput の GlobalHotKeys の書式）。"""

    start: str = _required("録音開始", reload=RELOAD_IMMEDIATE)
    pause: str = _required(
        "録音の一時停止・再開",
        reload=RELOAD_IMMEDIATE,
    )
    cancel: str = _required("録音の取り消し", reload=RELOAD_IMMEDIATE)


class KeyboardSettings(_SettingsModel):
    """貼り付け先へ送信する貼り付けのキー。"""

    paste_key: str = _required(
        "貼り付けのキーの組み合わせ（pynput の書式）", reload=RELOAD_IMMEDIATE
    )


# === 出力先 ===


class OutputSettingsBase(_SettingsModel):
    """出力先ごとの設定のモデルが継ぐ、どの出力先も持つ ID・オン・オフ・確定のホットキー。"""

    id: str = _item(..., "出力先の ID（設定の outputs[] の判別子）", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    hotkey: str = _item(..., "この出力先で確定するホットキー", reload=RELOAD_IMMEDIATE)


# === カスタムプリセット ===


class _PresetModel(_SettingsModel):
    """録音セッションが確定したときのコピーとして持つため、変えられないカスタムプリセットの共通の親。"""

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
    # repr に出さない: 設定や録音セッションを repr でログに出しても値が出ないようにする
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

    open_delay_sec: float = _required(
        "画面を開いてから貼り付けるまで待つ秒数", reload=RELOAD_IMMEDIATE, ge=0
    )


class EndpointPresetOptions(_SettingsModel):
    """エンドポイントへ送信の全てのプリセットで使う、送信のタイムアウト。"""

    timeout_sec: float = _required(
        "送信のタイムアウトの秒数",
        reload=RELOAD_IMMEDIATE,
        ge=ENDPOINT_TIMEOUT_MIN_SEC,
        le=ENDPOINT_TIMEOUT_MAX_SEC,
    )


class PresetOptions(_SettingsModel):
    """プリセットの種類ごとに、その種類の全てのプリセットで使う設定。"""

    browser: BrowserPresetOptions = _group("ブラウザ添付のオプション")
    endpoint: EndpointPresetOptions = _group("エンドポイントへ送信のオプション")


# === 履歴・ログ・画面・API ===


class HistorySettings(_SettingsModel):
    """履歴を残すかと保持期間。"""

    enabled: bool = _required("録音と起こした文字を履歴に残すか", reload=RELOAD_RESTART)
    retention_days: int = _required("保持する日数（1 以上）", reload=RELOAD_RESTART, ge=1)


class LoggingSettings(_SettingsModel):
    """ログのレベルと保持期間。"""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = _required(
        "ログのレベル", reload=RELOAD_RESTART
    )
    retention_days: int = _required(
        "日付ごとのログを保持する日数（1 以上）", reload=RELOAD_RESTART, ge=1
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
        description="画面の明暗。system は Windows の明暗に従う",
        json_schema_extra={"reload": RELOAD_IMMEDIATE, "choice_labels": THEME_LABELS},
    )
    topmost: bool = _required("常に最前面に表示するか", reload=RELOAD_IMMEDIATE)
    position: Literal["center", "top-left", "top-right", "bottom-left", "bottom-right"] = _required(
        "表示する位置", reload=RELOAD_IMMEDIATE
    )
    follow_cursor: bool = _required(
        "マウスカーソルのあるモニターに表示するか", reload=RELOAD_IMMEDIATE
    )
    wave_gain: float = _required(
        "波形の振れの大きさ（0 より大きい）", reload=RELOAD_IMMEDIATE, gt=0
    )
    show_hotkeys: bool = _required(
        "録音の画面のボタンにホットキーを表示するか", reload=RELOAD_IMMEDIATE
    )
    transcribing_show_hotkeys: bool = _required(
        "文字起こし中の表示のボタンにホットキーを表示するか", reload=RELOAD_IMMEDIATE
    )


class ContinuousSettings(_SettingsModel):
    """API で始めた連続録音の、区切りの無音の長さと録音セッションの上限時間。"""

    min_silence_sec: float = _required(
        "連続録音を区切る無音の長さ（0.5〜10 秒）。話し声の後にこの秒数以上無音が続いたところで区間を区切る",
        reload=RELOAD_RESTART,
        ge=0.5,
        le=10,
    )
    session_limit_sec: int = _required(
        "連続録音の録音セッションの上限時間（60〜86400 秒）。完了が来ないまま開始からこの秒数が経ったところで打ち切る",
        reload=RELOAD_RESTART,
        ge=60,
        le=86400,
    )


class ApiSettings(_SettingsModel):
    """API の待ち受けのポートと、返送を許すホスト、連続録音の設定。"""

    port: int = _required(
        "127.0.0.1 で待ち受けるポート（1024〜65535）",
        reload=RELOAD_RESTART,
        ge=1024,
        le=65535,
    )
    allowed_callback_hosts: list[str] = Field(
        description="loopback のほかに返送を許すホスト",
        json_schema_extra={"reload": RELOAD_RESTART},
    )
    continuous: ContinuousSettings = _group("連続録音の区切りと上限時間")
    allowed_web_origins: list[str] = Field(
        description=(
            "外の端末に許す Origin。`/web/` の下へ要求を送ってよいブラウザのオリジン"
            "（`https://{ゲートウェイの公開のサブドメイン}` の形。1 行に 1 つ）"
        ),
        json_schema_extra={"reload": RELOAD_RESTART},
    )

    @field_validator("allowed_web_origins")
    @classmethod
    def _origins_must_be_origin_form(cls, origins: list[str]) -> list[str]:
        """許す Origin が `scheme://host[:port]` の形式（末尾の `/` とパスが無い）であることを確かめる。"""
        invalid = [origin for origin in origins if not ORIGIN_PATTERN.fullmatch(origin)]
        # 形式の合わない Origin があれば断る
        if invalid:
            raise PydanticCustomError(
                WEB_ORIGIN_FORM_ERROR_TYPE,
                "`scheme://host[:port]` の形式で、末尾の `/` とパスを付けない（{origins}）",
                {"origins": ", ".join(invalid), "invalid": tuple(invalid)},
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
        description="その用語集の CSV の場所（settings.yaml のフォルダからの相対パスか絶対パス）"
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


def _check_hint_reading(reading: str) -> str:
    """読み 1 つの前後の空白を除き、空か、ひらがな・カタカナ・長音符だけであることを確かめる。"""
    stripped = reading.strip()
    # かな以外の文字を含む読みは断る
    if HINT_READING_PATTERN.fullmatch(stripped) is None:
        raise PydanticCustomError(HINT_READING_NOT_KANA_ERROR_TYPE, "読みにかな以外の文字がある")
    return stripped


type HintReading = Annotated[str, AfterValidator(_check_hint_reading)]
"""語の読み 1 つ。空文字は読みが無い語。_check_hint_reading で確かめる。"""


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
    readings: list[HintReading] = Field(
        default_factory=list,
        description="words と同じ並びの読み（各読みの前後の空白を除く）。空の一覧か words と同じ長さ。空文字は読みが無い語",
    )

    @model_validator(mode="after")
    def _readings_must_match_words(self) -> HintPresetSettings:
        """読みの数が語の数と合い、同じ語に違う読みが無いことを確かめる。"""
        # 読みの数が語の数と違えば、読みの場所で断る
        if self.readings and len(self.readings) != len(self.words):
            raise ValidationError.from_exception_data(
                type(self).__name__,
                [
                    {
                        "type": PydanticCustomError(
                            HINT_READINGS_LENGTH_ERROR_TYPE, "読みの数が語の数と合わない"
                        ),
                        "loc": ("readings",),
                        "input": self.readings,
                    }
                ],
            )
        # 同じ語に違う読みがあれば、後ろの語の読みの場所で断る（空の読みは比べない）
        first_readings: dict[str, str] = {}
        line_errors: list[InitErrorDetails] = []
        for index, (word, reading) in enumerate(zip(self.words, self.readings, strict=False)):
            if not reading:
                continue
            first = first_readings.setdefault(word, reading)
            if first != reading:
                line_errors.append(
                    {
                        "type": PydanticCustomError(
                            HINT_READING_CONFLICT_ERROR_TYPE, "同じ語に違う読みがある"
                        ),
                        "loc": ("readings", index),
                        "input": reading,
                    }
                )
        if line_errors:
            raise ValidationError.from_exception_data(type(self).__name__, line_errors)
        return self


class HintVocabularyWord(NamedTuple):
    """Haas へ渡す語 1 つの表記と読み。"""

    written: str
    reading: str | None


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
    """文頭・文末から削除する文言 1 行の文言と当てる位置。"""

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
        """`*` だけの文言（行を丸ごと削除する）を断る。空の文言はここでは断らない。"""
        # `*` だけで書かれた文言は、文頭・文末の行を丸ごと削除するため断る
        if text and not text.strip(EDGE_PHRASE_WILDCARD):
            raise PydanticCustomError(
                EDGE_PHRASE_WILDCARD_ONLY_ERROR_TYPE, "文言が * だけで、行を丸ごと削除してしまう"
            )
        return text


class Settings(_SettingsModel):
    """3 レイヤーを重ねた設定の全体。項目ごとに範囲・説明・再起動が要るかのマーカーを持つ。"""

    transcription: TranscriptionSettings = _group("使うエンジンと、エンジンごとの設定")
    recording: RecordingSettings = _group("録音中の音量・画面を出さない設定")
    hotkeys: HotkeySettings = _group("録音の開始・一時停止・取り消しのホットキー")
    keyboard: KeyboardSettings = _group("貼り付けのキー")
    outputs: list[SerializeAsAny[OutputSettingsBase]] = Field(
        description="出力先ごとのオン・オフ・確定のホットキー・出力先ごとの設定。ID は重ならない",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    history: HistorySettings = _group("履歴を残すか・保持期間")
    logging: LoggingSettings = _group("ログのレベル・保持期間")
    ui: UiSettings = _group("録音の画面の出し方")
    glossary_path: Path | None = _required(
        "今までの用語集の CSV。glossaries が空のときだけ使う。None は設定ファイルと同じフォルダの yogo.csv",
        reload=RELOAD_IMMEDIATE,
    )
    glossaries: list[GlossarySettings] = Field(
        description="用語集の一覧。並びが設定画面の一覧の並びになる。空のときは glossary_path の CSV を 1 つ目の用語集として扱う",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    active_glossary: str | None = _required(
        "補正に使う用語集の名前。glossary_presets が空のときだけ、「既定」のプリセットの用語集を決めるのに読む（非推奨。設定画面で保存すると削除する）",
        reload=RELOAD_IMMEDIATE,
    )
    glossary_presets: list[GlossaryPresetSettings] = Field(
        description="用語集のプリセットの一覧。並びが設定画面の一覧の並びになる。空なら「既定」の 1 件として読む",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    active_glossary_preset: str | None = _required(
        "補正に使う用語集のプリセットの名前。None か一覧に無い名前のときは 1 件目のプリセットを使う",
        reload=RELOAD_IMMEDIATE,
    )
    hint_presets: list[HintPresetSettings] = Field(
        description="表記のヒント（文字起こしの手がかり）のプリセットの一覧。並びが設定画面の一覧と語をつなぐ順になる。有効な語をつないだ長さが HINT_MAX_BYTES を超える設定は断る",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    edge_phrases: list[EdgePhraseSettings] = Field(
        description="起こした文字の文頭・文末から削除する文言の一覧。並びが当てる順と設定画面の一覧の並びになる。空の一覧なら何も削除しない。文言が空の行は一覧から除く",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    api: ApiSettings = _group("待ち受けのポート・返送を許すホスト")
    presets: list[Preset] = Field(
        description="カスタムプリセットの一覧。種類ごとの並びが、設定画面のタブと録音の画面のボタンの並びになる",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    preset_options: PresetOptions = _group("プリセットの種類ごとのオプション")

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
        # Haas のサーバーのポートが API のポートと同じなら、Haas のポートの場所で断る
        if self.transcription.haas.port == self.api.port:
            line_errors.append(
                {
                    "type": PydanticCustomError(
                        HAAS_PORT_OVERLAP_ERROR_TYPE, "API のポートと同じ番号"
                    ),
                    "loc": ("transcription", "haas", "port"),
                    "input": self.transcription.haas.port,
                }
            )
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
    """出力先の設定のモデルを受け、outputs をその判別共用体の一覧にした Settings の子のモデルを返す。"""
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

    # 3. outputs を既定値の無い必須の項目にする（既定の一覧は config/defaults.yaml が持つ。説明・反映のマーカーは Settings のものを引き継ぐ）
    base_field = Settings.model_fields[OUTPUTS_FIELD_NAME]
    outputs_field = Field(
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


def collect_hint_vocabulary(presets: Sequence[HintPresetSettings]) -> list[HintVocabularyWord]:
    """有効なプリセットの語を、一覧の上から順に表記と読みの組で返す。同じ表記は 1 つにまとめる。"""
    readings_by_word: dict[str, str | None] = {}
    for preset in presets:
        if not preset.enabled:
            continue
        for index, word in enumerate(preset.words):
            reading = (preset.readings[index] if preset.readings else "") or None
            # 同じ表記は最初の位置に残し、読みが無ければ後の語の読みを使う
            if readings_by_word.get(word) is None:
                readings_by_word[word] = reading
    return [HintVocabularyWord(word, reading) for word, reading in readings_by_word.items()]


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
    """`id = "ai_chat"` の出力先を外し、送信先をブラウザ添付のプリセットへ読み替えた dict を返す。"""
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
        # 2. 送信先（無ければ前の既定の 3 件）を並びのまま、ブラウザ添付のプリセットにして追加する
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


def _validate(model: type[Settings], data: dict[str, Any], *, paths: tuple[Path, ...]) -> Settings:
    """model で検証する。合わなければ、合わないキーを並べ、paths を持つ SettingsError を送出する。"""
    try:
        return model.model_validate(data)
    except ValidationError as error:
        failures = "、".join(f"{key}: {reason}" for key, reason in list_validation_failures(error))
        raise SettingsError(f"設定の値が合わない（{failures}）", paths=paths) from error


def _read_defaults(defaults_file: Path, *, os_kind: OsKind = CURRENT_OS) -> dict[str, Any]:
    """既定値のファイルを読み、os_overrides のうち os_kind の分を重ねて、os_overrides を外した dict を返す。"""
    # 1. 既定値のファイルが無ければ断る
    if not defaults_file.exists():
        raise SettingsError(
            f"設定ファイルを読めない（{defaults_file}: ファイルが無い）", paths=(defaults_file,)
        )

    # 2. 読む
    defaults = read_yaml_mapping(defaults_file)

    # 3. OS ごとの上書きを取り外し、os_kind の分があれば重ねる
    overrides = defaults.pop(DEFAULTS_OS_OVERRIDES_KEY, None) or {}
    override = overrides.get(os_kind.value)
    if override:
        return merge_layers(defaults, override)
    return defaults


def load_default_settings(
    defaults_file: Path, model: type[Settings], *, os_kind: OsKind = CURRENT_OS
) -> Settings:
    """既定値のファイルに、os_kind の上書きを重ねて検証した既定の設定を返す。"""
    return _validate(model, _read_defaults(defaults_file, os_kind=os_kind), paths=(defaults_file,))


def load_settings(paths: AppPaths, model: type[Settings]) -> Settings:
    """既定値 → 環境の値 → checkout の上書きの順に重ねて model で検証する。環境の値が無く settings.toml があれば、先に移す。"""
    # 1. 既定値を読む
    defaults = _read_defaults(paths.defaults_file)

    # 2. 環境の値が無く settings.toml があれば、先に移す
    if not paths.settings_file.exists() and paths.legacy_settings_file.exists():
        migrate_settings_toml(paths.legacy_settings_file, paths.settings_file, defaults)

    # 3. 環境の値と checkout の上書きを読む（無いファイルは空。checkout の上書きを読まない起動は飛ばす）
    read_files = [paths.defaults_file]
    layers = [defaults]
    for layer_file in (paths.settings_file, paths.local_settings_file):
        if layer_file is None or not layer_file.exists():
            continue
        read_files.append(layer_file)
        # 古い AI チャットの設定はレイヤーごとに読み替える（重ねた後では既定値の preset_options が先にあり、移す値が負けるため）
        layers.append(migrate_ai_chat(read_yaml_mapping(layer_file)))

    # 4. 重ねて検証する（合わないときは、読んだ環境の値・checkout の上書きのファイルを示す。どちらも読んでいなければ既定値のファイル）
    layer_files = tuple(read_files[1:]) or (paths.defaults_file,)
    settings = _validate(model, merge_layers(*layers), paths=layer_files)
    logger.info(f"設定を読んだ（{'・'.join(str(path) for path in read_files)}）")
    return settings


# === 書き戻し ===


def _dump_settings(settings: Settings, settings_dir: Path) -> dict[str, Any]:
    """設定を JSON の値にする。用語集の場所は、設定のフォルダの下なら相対パス（区切りは `/`）にする。"""
    data = settings.model_dump(mode="json")
    for glossary in data.get(GLOSSARIES_FIELD_NAME, []):
        glossary_path = Path(glossary["path"])
        if glossary_path.is_relative_to(settings_dir):
            glossary["path"] = glossary_path.relative_to(settings_dir).as_posix()
    return data


def _value_at(data: Mapping[str, Any], key: tuple[str, ...]) -> Any:
    """入れ子の dict から key の値を返す。途中に無ければ None。"""
    value: Any = data
    for name in key:
        if not isinstance(value, Mapping) or name not in value:
            return None
        value = value[name]
    return value


def _has_ai_chat(document: Mapping[str, Any]) -> bool:
    """文書の outputs に古い AI チャットの項目があるか。"""
    outputs = document.get(OUTPUTS_FIELD_NAME)
    return isinstance(outputs, list) and any(
        isinstance(output, Mapping) and output.get("id") == AI_CHAT_ID for output in outputs
    )


def save_settings(paths: AppPaths, previous: Settings, settings: Settings) -> bool:
    """前の設定から変わったキーだけを環境の値に書き、既定値と同じ値にしたキーは外す。再起動が要る項目が変わったかを返す。"""
    # 1. 前の設定・新しい設定・既定の設定を JSON の値にする
    settings_dir = paths.settings_file.parent
    before = _dump_settings(previous, settings_dir)
    after = _dump_settings(settings, settings_dir)
    defaults = _dump_settings(
        load_default_settings(paths.defaults_file, type(settings)), settings_dir
    )

    # 2. 値が変わったキーを集める
    keys = changed_keys(before, after)

    # 3. 環境の値を読む（読めなければ書き換えずに断る）
    document = read_yaml_document(paths.settings_file)
    # 古い AI チャットの項目が残っていれば、読み替えた値を書いて古い項目を残さない
    if _has_ai_chat(document):
        keys += [(OUTPUTS_FIELD_NAME,), (PRESETS_FIELD_NAME,)]
        keys += [
            (PRESET_OPTIONS_FIELD_NAME, *key)
            for key in changed_keys({}, after[PRESET_OPTIONS_FIELD_NAME])
        ]

    # 4. 既定値と同じか None にしたキーは外し、違えば書く
    for key in dict.fromkeys(keys):
        value = _value_at(after, key)
        if value is None or value == _value_at(defaults, key):
            delete_key(document, key)
        else:
            set_key(document, key, value)

    # 5. 同じフォルダの一時ファイルへ書いて置き換える
    write_yaml_document(paths.settings_file, document)

    # 6. 再起動が要る項目が変わったか
    return has_restart_change(previous, settings)


def has_restart_change(previous: BaseModel, settings: BaseModel) -> bool:
    """再起動が要るマーカーの項目のうち、値が違うものがあるか。"""
    for name, field in type(settings).model_fields.items():
        before = getattr(previous, name)
        after = getattr(settings, name)
        # 入れ子のまとまり: 中の項目を見る
        if isinstance(after, BaseModel):
            if has_restart_change(before, after):
                return True
            continue
        extra = field.json_schema_extra
        reload = extra.get("reload") if isinstance(extra, dict) else None
        # 再起動が要るマーカーの項目の値が変わったか
        if reload == RELOAD_RESTART and before != after:
            return True
    return False


def reset_settings(settings_file: Path) -> None:
    """環境の値から全てのキーを外す。無ければ何もしない。"""
    # 1. 環境の値が無ければ作らない
    if not settings_file.exists():
        return

    # 2. 読み、一番上のキーを全て外して書く（読めなければ空の文書で置き換える）
    try:
        document = read_yaml_document(settings_file)
    except SettingsError:
        write_yaml_document(settings_file, {})
        return
    for name in list(document):
        delete_key(document, (name,))
    write_yaml_document(settings_file, document)


# === settings.toml からの移行 ===


def inherit_transcribing_show_hotkeys(layer: dict[str, Any]) -> dict[str, Any]:
    """show_hotkeys を持ち transcribing_show_hotkeys を持たない ui へ、show_hotkeys の値を入れたコピーを返す。"""
    ui = layer.get("ui")
    # ui が表でない・文字起こし中の表示の項目がある・録音の画面の項目が無い: そのまま返す（どちらも無ければ既定値に任せる）
    if not isinstance(ui, dict) or "transcribing_show_hotkeys" in ui or "show_hotkeys" not in ui:
        return layer
    # 項目が無い: 録音の画面の値を入れたコピーを返す（layer は書き換えない）
    return {**layer, "ui": {**ui, "transcribing_show_hotkeys": ui["show_hotkeys"]}}


def migrate_settings_toml(
    legacy_settings_file: Path, settings_file: Path, defaults: dict[str, Any]
) -> None:
    """settings.toml を読み、既定値と違うキーだけを settings.yaml に書く。settings.toml は残す。"""
    # 1. settings.toml を読んで素の dict にする（読めなければ settings.yaml を作らずに断る）
    try:
        legacy = tomlkit.parse(legacy_settings_file.read_text(encoding="utf-8")).unwrap()
    except TOMLKitError as error:
        raise SettingsError(
            f"設定ファイルを読めない（{legacy_settings_file}: {error}）", paths=(legacy_settings_file,)
        ) from error

    # 2. 古い AI チャットの設定を読み替え、文字起こし中の表示のホットキーを引き継ぐ
    migrated = inherit_transcribing_show_hotkeys(migrate_ai_chat(legacy))

    # 3. 既定値と違うキーだけを書く
    diff = diff_from_defaults(migrated, defaults)
    write_yaml_document(settings_file, diff)
    logger.info(
        f"settings.toml から settings.yaml へ移した（{legacy_settings_file} → {settings_file}・{len(diff)} キー）"
    )
