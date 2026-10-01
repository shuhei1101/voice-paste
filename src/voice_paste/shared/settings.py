"""設定のモデル（pydantic）と、settings.toml の読み書き（tomlkit）。"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any, Literal

import tomlkit
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from tomlkit.exceptions import TOMLKitError

from voice_paste.shared.errors import SettingsError

logger = logging.getLogger(__name__)

RELOAD_IMMEDIATE: str = "immediate"
"""設定画面で保存すると、動いている常駐アプリに効く項目の印。"""

RELOAD_RESTART: str = "restart"
"""再起動してから効く項目の印。"""

OUTPUTS_FIELD_NAME: str = "outputs"
"""出力先の一覧を持つ Settings の項目名。"""

OUTPUT_DISCRIMINATOR_INDEX: int = 2
"""出力先の失敗の場所（outputs・添字・判別子の値・…）で、判別子の値が入る位置。"""


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
        "録音の画面も文字起こし中の表示も出さず、トレイとホットキーだけで操作するか",
        reload=RELOAD_IMMEDIATE,
    )


class HotkeySettings(_SettingsModel):
    """録音の開始・一時停止・取り消しのホットキー（pynput の GlobalHotKeys の書式）。"""

    start: str = _item("<ctrl>+<alt>+d", "録音を始める", reload=RELOAD_IMMEDIATE)
    pause: str = _item("<ctrl>+<alt>+z", "録音を一時停止・再開する", reload=RELOAD_IMMEDIATE)
    cancel: str = _item("<ctrl>+<alt>+q", "録音を取り消す", reload=RELOAD_IMMEDIATE)


class KeyboardSettings(_SettingsModel):
    """貼り付け先へ送る貼り付けのキー。"""

    paste_key: str = _item(
        "<ctrl>+v", "貼り付けのキーの組み合わせ（pynput の書式）", reload=RELOAD_IMMEDIATE
    )


# === 出力先 ===


class PasteAndSendSettings(_SettingsModel):
    """出力先 paste_and_send（貼り付けて送信）の設定。"""

    id: Literal["paste_and_send"] = _item(
        "paste_and_send", "出力先の ID（OutputSettings の判別子）", reload=RELOAD_IMMEDIATE
    )
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    hotkey: str = _item(
        "<ctrl>+<alt>+d", "この出力先で確定するホットキー", reload=RELOAD_IMMEDIATE
    )
    enter_delay_sec: float = _item(
        0.5, "貼り付けてから Enter を送るまで待つ秒数", reload=RELOAD_IMMEDIATE, ge=0
    )


class PasteOnlySettings(_SettingsModel):
    """出力先 paste_only（貼り付けのみ）の設定。"""

    id: Literal["paste_only"] = _item("paste_only", "出力先の ID", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    hotkey: str = _item(
        "<ctrl>+<alt>+v", "この出力先で確定するホットキー", reload=RELOAD_IMMEDIATE
    )


class CopyOnlySettings(_SettingsModel):
    """出力先 copy_only（コピーのみ）の設定。"""

    id: Literal["copy_only"] = _item("copy_only", "出力先の ID", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    hotkey: str = _item(
        "<ctrl>+<alt>+c", "この出力先で確定するホットキー", reload=RELOAD_IMMEDIATE
    )


class AiChatTarget(_SettingsModel):
    """AI チャットの送り先 1 件。"""

    name: str = _item(..., "画面に出す名前（1 文字以上）", reload=RELOAD_IMMEDIATE, min_length=1)
    url: str = _item(
        ...,
        "Microsoft Edge の `--app` で開く URL（http か https）",
        reload=RELOAD_IMMEDIATE,
        pattern=r"^https?://",
    )
    hotkey: str = _item(..., "この送り先へ送る確定のホットキー", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(
        True, "画面にボタンを出し、ホットキーを登録するか", reload=RELOAD_IMMEDIATE
    )


def _default_ai_chat_targets() -> list[AiChatTarget]:
    """既定の送り先（ChatGPT・Google AI・Claude）を返す。"""
    return [
        AiChatTarget(name="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1"),
        AiChatTarget(
            name="Google AI", url="https://gemini.google.com/app", hotkey="<ctrl>+<alt>+2"
        ),
        AiChatTarget(name="Claude", url="https://claude.ai/new", hotkey="<ctrl>+<alt>+3"),
    ]


class AiChatSettings(_SettingsModel):
    """出力先 ai_chat（AI チャットへ送る）の設定。"""

    id: Literal["ai_chat"] = _item("ai_chat", "出力先の ID", reload=RELOAD_IMMEDIATE)
    enabled: bool = _item(True, "オンか", reload=RELOAD_IMMEDIATE)
    open_delay_sec: float = _item(
        3.0,
        "AI チャットの画面を開いてから貼り付けるまで待つ秒数",
        reload=RELOAD_IMMEDIATE,
        ge=0,
    )
    targets: list[AiChatTarget] = Field(
        default_factory=_default_ai_chat_targets,
        description="送り先の一覧。確定のホットキーは送り先ごとに持つ",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )


OutputSettings = Annotated[
    PasteAndSendSettings | PasteOnlySettings | CopyOnlySettings | AiChatSettings,
    Field(discriminator="id"),
]
"""出力先ごとの設定の判別共用体（`id` で見分ける）。"""


def _default_outputs() -> list[OutputSettings]:
    """既定の出力先の一覧（paste_and_send・paste_only・copy_only・ai_chat の順）を返す。"""
    return [PasteAndSendSettings(), PasteOnlySettings(), CopyOnlySettings(), AiChatSettings()]


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


class UiSettings(_SettingsModel):
    """録音の画面と文字起こし中の表示の出し方。"""

    topmost: bool = _item(True, "常に最前面に出すか", reload=RELOAD_IMMEDIATE)
    position: Literal["center", "top-left", "top-right", "bottom-left", "bottom-right"] = _item(
        "center", "出す位置", reload=RELOAD_IMMEDIATE
    )
    follow_cursor: bool = _item(
        True, "マウスカーソルのあるモニターに出すか", reload=RELOAD_IMMEDIATE
    )
    wave_gain: float = _item(
        4, "波形の振れの大きさ（0 より大きい）", reload=RELOAD_IMMEDIATE, gt=0
    )


class ApiSettings(_SettingsModel):
    """API の待ち受けのポートと、返送を許すホスト。"""

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
    outputs: list[OutputSettings] = Field(
        default_factory=_default_outputs,
        description="出力先ごとのオン・オフ・確定のホットキー・出力先ごとの設定。ID は重ならない",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    history: HistorySettings = _group(HistorySettings, "履歴を残すか・保持期間")
    logging: LoggingSettings = _group(LoggingSettings, "ログのレベル・保持期間")
    ui: UiSettings = _group(UiSettings, "録音の画面の出し方")
    glossary_path: Path | None = _item(
        None,
        "用語集の CSV。None は設定ファイルと同じフォルダの yogo.csv",
        reload=RELOAD_IMMEDIATE,
    )
    api: ApiSettings = _group(ApiSettings, "待ち受けのポート・返送を許すホスト")

    @field_validator(OUTPUTS_FIELD_NAME)
    @classmethod
    def _output_ids_must_be_unique(cls, outputs: list[OutputSettings]) -> list[OutputSettings]:
        """出力先の ID が一覧の中で重ならないことを確かめる。"""
        ids = [output.id for output in outputs]
        duplicated = sorted({output_id for output_id in ids if ids.count(output_id) > 1})
        # 重なる ID があれば断る
        if duplicated:
            raise ValueError(f"出力先の ID が重なる（{', '.join(duplicated)}）")
        return outputs


# === 検証の失敗の整形 ===


def format_error_location(location: tuple[int | str, ...]) -> str:
    """pydantic の失敗の場所をドット区切り（添字は `[0]`）のキーにする。"""
    parts = list(location)
    # 出力先の判別共用体は、添字の次に判別子の値（paste_only など）が入るので外す
    if (
        len(parts) > OUTPUT_DISCRIMINATOR_INDEX
        and parts[0] == OUTPUTS_FIELD_NAME
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


# === 読み込み ===


def load_settings(path: Path) -> Settings:
    """settings.toml を読んで検証する。無ければ既定値で作る。"""
    # 1. 設定ファイルが無いか
    if not path.exists():
        # 無い: 既定の設定を書いて返す
        settings = Settings()
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
        return Settings.model_validate(document.unwrap())
    except ValidationError as error:
        failures = "、".join(f"{key}: {reason}" for key, reason in list_validation_failures(error))
        raise SettingsError(f"設定の値が合わない（{failures}）") from error


# === 書き戻し ===


def save_settings(path: Path, settings: Settings) -> bool:
    """検証した設定をコメントを保ったまま書き戻し、再起動が要る項目が変わったかを返す。"""
    # 1・2. 既にある設定ファイルを読み、前の設定にする
    document, previous, unreadable = _read_existing(path)

    # 3. 設定を JSON の値にする
    data = settings.model_dump(mode="json", exclude_none=True)

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


def _read_existing(path: Path) -> tuple[tomlkit.TOMLDocument, Settings | None, bool]:
    """既にある settings.toml を（文書, 前の設定, 読めないか）にして返す。"""
    # 設定ファイルが無いか
    if not path.exists():
        return tomlkit.document(), None, False

    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
        return document, Settings.model_validate(document.unwrap()), False
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

    # 表の後に置くとその表のキーとして読まれる値を、先に並べる
    for key, value in sorted(source.items(), key=lambda entry: _is_table_like(entry[1])):
        existing = target.get(key)
        # 表: 既にある表の中を再帰で置き換える
        if isinstance(value, dict) and isinstance(existing, MutableMapping):
            _merge_into(existing, value)
        # 値が変わっていなければ書式とコメントのために触らない
        elif key not in target or _unwrap(existing) != value:
            target[key] = value


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
