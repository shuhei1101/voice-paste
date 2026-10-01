"""voice_paste_legacy の .env を読み、settings.toml のキーへ写した設定を作る。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import ValidationError

from voice_paste.shared.errors import SettingsError
from voice_paste.shared.settings import Settings, list_validation_failures

logger = logging.getLogger(__name__)

ENGINE_ENV_KEY: str = "TRANSCRIPTION_ENGINE"
"""文字起こしのエンジンを書く .env のキー。"""

ENGINE_NAMES: dict[str, str] = {"local": "local_whisper"}
"""`.env` のエンジンの値 → settings.toml のエンジンの値。"""

GLOSSARY_ENV_KEY: str = "YOGO_FILE"
"""用語集の場所を書く .env のキー。"""

GLOSSARY_FILE_NAME: str = "yogo.csv"
"""用語集の既定のファイル名。"""

GLOSSARY_RESOURCES_DIR_NAME: str = "resources"
"""同梱の用語集を置くフォルダ名。"""

AI_SEND_FIRST_NUMBER: int = 1
"""AI 送信の設定（`AI_SEND_{n}_*`）の最初の番号。"""

AI_SEND_FIELDS: tuple[str, ...] = ("name", "url", "hotkey", "enabled")
"""AI 送信の設定（`AI_SEND_{n}_*`）が持つ項目。大文字にすると .env のキーの末尾になる。"""

PLAIN_MAPPINGS: dict[str, tuple[str, ...]] = {
    "WHISPER_MODEL": ("transcription.local_whisper.model",),
    "WHISPER_DEVICE": ("transcription.local_whisper.device",),
    "WHISPER_COMPUTE_TYPE": ("transcription.local_whisper.compute_type",),
    "WHISPER_CPU_THREADS": ("transcription.local_whisper.cpu_threads",),
    "WHISPER_NUM_WORKERS": ("transcription.local_whisper.num_workers",),
    "WHISPER_BEAM_SIZE": ("transcription.local_whisper.beam_size",),
    "WHISPER_BEST_OF": ("transcription.local_whisper.best_of",),
    "WHISPER_LANGUAGE": ("transcription.local_whisper.language",),
    "WHISPER_VAD_FILTER": ("transcription.local_whisper.vad_filter",),
    "WHISPER_VAD_THRESHOLD": ("transcription.local_whisper.vad_threshold",),
    "WHISPER_VAD_MIN_SPEECH_MS": ("transcription.local_whisper.vad_min_speech_ms",),
    "WHISPER_VAD_MIN_SILENCE_MS": ("transcription.local_whisper.vad_min_silence_ms",),
    "WHISPER_CONDITION_ON_PREVIOUS_TEXT": (
        "transcription.local_whisper.condition_on_previous_text",
    ),
    "WHISPER_TEMPERATURE": ("transcription.local_whisper.temperature",),
    "WHISPER_NO_SPEECH_THRESHOLD": ("transcription.local_whisper.no_speech_threshold",),
    "LOG_LEVEL": ("logging.level",),
    "RESIDENT_HOTKEY": ("hotkeys.start",),
    "PAUSE_HOTKEY": ("hotkeys.pause",),
    "CANCEL_HOTKEY": ("hotkeys.cancel",),
    "PASTE_KEY": ("keyboard.paste_key",),
    "HISTORY_ENABLED": ("history.enabled",),
    "HISTORY_RETENTION_DAYS": ("history.retention_days",),
    "WINDOW_TOPMOST": ("ui.topmost",),
    "WINDOW_POSITION": ("ui.position",),
    "WINDOW_FOLLOW_CURSOR": ("ui.follow_cursor",),
    "WINDOW_HIDDEN": ("recording.hide_window",),
    "WAVE_GAIN": ("ui.wave_gain",),
    "RECORDING_VOLUME_ENABLED": ("recording.lower_volume",),
    "RECORDING_VOLUME": ("recording.volume_percent",),
    "RECORDING_VOLUME_FADE_DURATION": ("recording.fade_sec",),
}
"""`.env` のキー → settings.toml のキー（`.` 区切り）。"""

BOOL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "WHISPER_VAD_FILTER",
        "WHISPER_CONDITION_ON_PREVIOUS_TEXT",
        "HISTORY_ENABLED",
        "WINDOW_TOPMOST",
        "WINDOW_FOLLOW_CURSOR",
        "WINDOW_HIDDEN",
        "RECORDING_VOLUME_ENABLED",
    }
)
"""小文字にして `true` のときだけ真として読む .env のキー。"""

OUTPUT_IDS: tuple[str, ...] = ("paste_and_send", "paste_only", "copy_only", "ai_chat")
"""出力先の一覧の並び（Settings の既定と同じ）。"""

OUTPUT_MAPPINGS: dict[str, tuple[str, str]] = {
    "CONFIRM_HOTKEY": ("paste_and_send", "hotkey"),
    "PASTE_ENTER_DELAY": ("paste_and_send", "enter_delay_sec"),
    "CONFIRM_PASTE_ONLY_HOTKEY": ("paste_only", "hotkey"),
    "COPY_ONLY_HOTKEY": ("copy_only", "hotkey"),
    "AI_SEND_DELAY": ("ai_chat", "open_delay_sec"),
}
"""`.env` のキー → （出力先の ID, その出力先の項目）。"""

AI_CHAT_ID: str = "ai_chat"
"""AI チャットの出力先の ID。"""


def _to_bool(value: str) -> bool:
    """小文字にして `true` のときだけ真にする（voice_paste_legacy の読み方）。"""
    return value.lower() == "true"


def _assign(data: dict[str, Any], dotted_key: str, value: Any) -> None:
    """`.` 区切りのキーの位置に、入れ子の dict を作りながら値を置く。"""
    *parents, last = dotted_key.split(".")
    node = data
    for parent in parents:
        node = node.setdefault(parent, {})
    node[last] = value


def _resolve_glossary(yogo_file: str | None, base: Path) -> Path:
    """用語集の場所を voice_paste_legacy と同じ順で base を基準に解く。"""
    root_candidate = base / GLOSSARY_FILE_NAME
    # YOGO_FILE が空・無いか
    if not yogo_file:
        # 空・無い: 直下の yogo.csv があればそれ、無ければ resources/yogo.csv
        if root_candidate.exists():
            return root_candidate
        return base / GLOSSARY_RESOURCES_DIR_NAME / GLOSSARY_FILE_NAME

    specified = Path(yogo_file)
    # 絶対パス: そのまま
    if specified.is_absolute():
        return specified
    # 相対パス: 直下の yogo.csv → 指定の相対パス → resources/{ファイル名} の順で最初にあるもの
    if root_candidate.exists():
        return root_candidate
    relative_candidate = base / specified
    if relative_candidate.exists():
        return relative_candidate
    bundled_candidate = base / GLOSSARY_RESOURCES_DIR_NAME / specified.name
    if bundled_candidate.exists():
        return bundled_candidate
    return root_candidate


def _read_ai_chat_targets(
    values: dict[str, str | None], locations: dict[str, str]
) -> tuple[list[dict[str, Any]], set[str]]:
    """AI_SEND_{n}_* を 1 番から、名前か URL が空の番号で止めて送り先の一覧にする。"""
    ai_chat_index = OUTPUT_IDS.index(AI_CHAT_ID)
    targets: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    number = AI_SEND_FIRST_NUMBER
    while True:
        prefix = f"AI_SEND_{number}_"
        name = (values.get(f"{prefix}NAME") or "").strip()
        url = (values.get(f"{prefix}URL") or "").strip()
        # 名前か URL が空の番号で止める
        if not name or not url:
            return targets, used_keys

        index = len(targets)
        target: dict[str, Any] = {"name": name, "url": url}
        hotkey = (values.get(f"{prefix}HOTKEY") or "").strip()
        # ホットキーが空なら既定（<ctrl>+<alt>+{番号}）
        target["hotkey"] = hotkey or f"<ctrl>+<alt>+{number}"
        enabled = values.get(f"{prefix}ENABLED")
        # 有効かが書かれていれば真偽に直す（空なら既定の真）
        if enabled:
            target["enabled"] = _to_bool(enabled)

        output_prefix = f"outputs[{ai_chat_index}].targets[{index}]"
        for field in AI_SEND_FIELDS:
            env_key = f"{prefix}{field.upper()}"
            locations[f"{output_prefix}.{field}"] = env_key
            used_keys.add(env_key)
        targets.append(target)
        number += 1


def migrate_env(env_path: Path) -> Settings:
    """voice_paste_legacy の .env を読むだけで、値を settings.toml のキーへ写した Settings を返す。"""
    # 1. .env を環境変数へ入れず読む
    if not env_path.exists():
        raise SettingsError(f".env が無い（{env_path}）")
    values: dict[str, str | None] = dict(dotenv_values(env_path))

    data: dict[str, Any] = {}
    # 検証の失敗の場所（settings.toml のキー）→ 元の .env のキー
    locations: dict[str, str] = {}
    used_keys: set[str] = (
        set(PLAIN_MAPPINGS) | set(OUTPUT_MAPPINGS) | {ENGINE_ENV_KEY, GLOSSARY_ENV_KEY}
    )

    # 2. 対応表のキーごとに、値があって空でないものだけを写す
    engine = values.get(ENGINE_ENV_KEY)
    if engine:
        # エンジンは local → local_whisper に読み替える（local 以外は断る）
        if engine not in ENGINE_NAMES:
            raise SettingsError(f".env の値が合わない（{ENGINE_ENV_KEY}: {engine}）")
        _assign(data, "transcription.engine", ENGINE_NAMES[engine])
        locations["transcription.engine"] = ENGINE_ENV_KEY

    for env_key, setting_keys in PLAIN_MAPPINGS.items():
        value = values.get(env_key)
        if not value:
            continue
        # bool のキーは真偽に直し、それ以外は文字のまま渡して検証で型を直す
        converted: Any = _to_bool(value) if env_key in BOOL_ENV_KEYS else value
        for setting_key in setting_keys:
            _assign(data, setting_key, converted)
            locations[setting_key] = env_key

    # 3. 用語集の場所を解いて絶対パスで写す（YOGO_FILE が空・無いときも写す）
    base = env_path.resolve().parent
    data["glossary_path"] = _resolve_glossary(values.get(GLOSSARY_ENV_KEY), base)

    # 4. 送り先の一覧を作る
    targets, target_keys = _read_ai_chat_targets(values, locations)
    used_keys |= target_keys

    # 5. 既定の並びの出力先の一覧へ、確定のホットキー・待ち時間・送り先を写す
    outputs: list[dict[str, Any]] = [{"id": output_id} for output_id in OUTPUT_IDS]
    for env_key, (output_id, field) in OUTPUT_MAPPINGS.items():
        value = values.get(env_key)
        if not value:
            continue
        index = OUTPUT_IDS.index(output_id)
        outputs[index][field] = value
        locations[f"outputs[{index}].{field}"] = env_key
    outputs[OUTPUT_IDS.index(AI_CHAT_ID)]["targets"] = targets
    data["outputs"] = outputs

    # 6. 対応表に無いキーは写さずにログへ書く
    unmoved = sorted(set(values) - used_keys)
    if unmoved:
        logger.warning(f"移さなかった .env のキー（{', '.join(unmoved)}）")

    # 7. 検証して返す
    try:
        return Settings.model_validate(data)
    except ValidationError as error:
        reasons: dict[str, str] = {}
        for location, reason in list_validation_failures(error):
            # 同じ .env のキーから写した複数の項目の失敗は、最初の理由だけ並べる
            reasons.setdefault(locations.get(location, location), reason)
        detail = "、".join(f"{key}: {reason}" for key, reason in reasons.items())
        raise SettingsError(f".env の値が合わない（{detail}）") from error
