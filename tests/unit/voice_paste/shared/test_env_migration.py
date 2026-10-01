"""shared/env_migration.py（migrate_env）の単体テスト。"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytest

# 全てのキーに既定と違う値を書いた .env（{glossary} は用語集の絶対パス）
CUSTOM_ENV_TEMPLATE = """\
TRANSCRIPTION_ENGINE=openai
OPENAI_API_KEY=sk-custom
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_CPU_THREADS=4
WHISPER_NUM_WORKERS=2
WHISPER_BEAM_SIZE=3
WHISPER_BEST_OF=2
WHISPER_LANGUAGE=en
WHISPER_VAD_FILTER=False
WHISPER_VAD_THRESHOLD=0.4
WHISPER_VAD_MIN_SPEECH_MS=300
WHISPER_VAD_MIN_SILENCE_MS=1500
WHISPER_CONDITION_ON_PREVIOUS_TEXT=TRUE
WHISPER_TEMPERATURE=0.2
WHISPER_NO_SPEECH_THRESHOLD=0.7
YOGO_FILE={glossary}
LOG_LEVEL=DEBUG
RESIDENT_MODE=false
RESIDENT_HOTKEY=<ctrl>+<alt>+s
CONFIRM_HOTKEY=<ctrl>+<alt>+e
CONFIRM_PASTE_ONLY_HOTKEY=<ctrl>+<alt>+p
CANCEL_HOTKEY=<ctrl>+<alt>+x
COPY_ONLY_HOTKEY=<ctrl>+<alt>+y
PAUSE_HOTKEY=<ctrl>+<alt>+w
PASTE_KEY=<ctrl>+<shift>+v
PASTE_ENTER_DELAY=1.5
AI_SEND_1_ENABLED=False
AI_SEND_1_NAME=Alpha
AI_SEND_1_URL=https://alpha.example.com
AI_SEND_1_HOTKEY=<ctrl>+<alt>+8
AI_SEND_2_ENABLED=TRUE
AI_SEND_2_NAME=Beta
AI_SEND_2_URL=https://beta.example.com
AI_SEND_2_HOTKEY=<ctrl>+<alt>+9
AI_SEND_DELAY=5.0
HISTORY_ENABLED=False
HISTORY_RETENTION_DAYS=3
WINDOW_TOPMOST=False
WINDOW_POSITION=top-left
WINDOW_FOLLOW_CURSOR=False
WINDOW_HIDDEN=TRUE
WAVE_GAIN=8
RECORDING_VOLUME_ENABLED=False
RECORDING_VOLUME=30
RECORDING_VOLUME_FADE_DURATION=1.0
"""


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    """一時フォルダの .env のパスを返す（ファイルはまだ無い）。"""
    return tmp_path / ".env"


@pytest.fixture
def sample_env(env_path: Path, repo_root: Path) -> Path:
    """リポジトリの .env.sample を一時フォルダへ写した .env を返す。"""
    shutil.copyfile(repo_root / ".env.sample", env_path)
    return env_path


def _write_files(base: Path, relative_paths: list[str]) -> None:
    """base の下に relative_paths の空のファイルを置く（途中のフォルダも作る）。"""
    for relative_path in relative_paths:
        file_path = base / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("", encoding="utf-8")


def test_migrate_env_when_sample(
    sample_env: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """.env.sample の全キーを写す（正常系）。"""
    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.settings import Settings

    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    settings = migrate_env(sample_env)

    # 検証（.env.sample の値と既定値が一致し、用語集だけが解いた絶対パスになる）
    assert settings == Settings(glossary_path=tmp_path / "resources" / "yogo.csv")
    assert "WARNING" in caplog.text
    assert "RESIDENT_MODE" in caplog.text


def test_migrate_env_when_custom_values(env_path: Path, tmp_path: Path) -> None:
    """既定と違う値を対応するキーへ写す（正常系）。"""
    from pydantic import SecretStr

    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.settings import (
        AiChatSettings,
        AiChatTarget,
        CopyOnlySettings,
        HistorySettings,
        HotkeySettings,
        KeyboardSettings,
        LocalWhisperSettings,
        LoggingSettings,
        OpenAISettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        RecordingSettings,
        Settings,
        TranscriptionSettings,
        UiSettings,
    )

    # 準備
    glossary = tmp_path / "custom_yogo.csv"
    env_path.write_text(
        CUSTOM_ENV_TEMPLATE.format(glossary=glossary), encoding="utf-8"
    )

    # 実行
    settings = migrate_env(env_path)

    # 検証
    assert settings == Settings(
        transcription=TranscriptionSettings(
            engine="openai",
            local_whisper=LocalWhisperSettings(
                model="small",
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                num_workers=2,
                beam_size=3,
                best_of=2,
                language="en",
                vad_filter=False,
                vad_threshold=0.4,
                vad_min_speech_ms=300,
                vad_min_silence_ms=1500,
                condition_on_previous_text=True,
                temperature=0.2,
                no_speech_threshold=0.7,
            ),
            openai=OpenAISettings(
                api_key=SecretStr("sk-custom"), language="en", temperature=0.2
            ),
        ),
        recording=RecordingSettings(
            lower_volume=False, volume_percent=30, fade_sec=1.0, hide_window=True
        ),
        hotkeys=HotkeySettings(
            start="<ctrl>+<alt>+s", pause="<ctrl>+<alt>+w", cancel="<ctrl>+<alt>+x"
        ),
        keyboard=KeyboardSettings(paste_key="<ctrl>+<shift>+v"),
        outputs=[
            PasteAndSendSettings(hotkey="<ctrl>+<alt>+e", enter_delay_sec=1.5),
            PasteOnlySettings(hotkey="<ctrl>+<alt>+p"),
            CopyOnlySettings(hotkey="<ctrl>+<alt>+y"),
            AiChatSettings(
                open_delay_sec=5.0,
                targets=[
                    AiChatTarget(
                        name="Alpha",
                        url="https://alpha.example.com",
                        hotkey="<ctrl>+<alt>+8",
                        enabled=False,
                    ),
                    AiChatTarget(
                        name="Beta",
                        url="https://beta.example.com",
                        hotkey="<ctrl>+<alt>+9",
                        enabled=True,
                    ),
                ],
            ),
        ],
        history=HistorySettings(enabled=False, retention_days=3),
        logging=LoggingSettings(level="DEBUG"),
        ui=UiSettings(
            topmost=False, position="top-left", follow_cursor=False, wave_gain=8
        ),
        glossary_path=glossary,
    )


def test_migrate_env_when_ai_send_gap(env_path: Path, tmp_path: Path) -> None:
    """送り先は空の番号で止める（正常系）。"""
    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.settings import (
        AiChatSettings,
        AiChatTarget,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        Settings,
    )

    # 準備（3 番が無く 4 番がある）
    env_path.write_text(
        "AI_SEND_1_NAME=Alpha\n"
        "AI_SEND_1_URL=https://alpha.example.com\n"
        "AI_SEND_2_NAME=Beta\n"
        "AI_SEND_2_URL=https://beta.example.com\n"
        "AI_SEND_4_NAME=Delta\n"
        "AI_SEND_4_URL=https://delta.example.com\n",
        encoding="utf-8",
    )

    # 実行
    settings = migrate_env(env_path)

    # 検証（ai_chat の送り先が 1・2 の 2 件）
    assert settings == Settings(
        outputs=[
            PasteAndSendSettings(),
            PasteOnlySettings(),
            CopyOnlySettings(),
            AiChatSettings(
                targets=[
                    AiChatTarget(
                        name="Alpha",
                        url="https://alpha.example.com",
                        hotkey="<ctrl>+<alt>+1",
                    ),
                    AiChatTarget(
                        name="Beta",
                        url="https://beta.example.com",
                        hotkey="<ctrl>+<alt>+2",
                    ),
                ]
            ),
        ],
        glossary_path=tmp_path / "resources" / "yogo.csv",
    )


@pytest.mark.parametrize(
    ("existing_files", "expected_glossary"),
    [
        pytest.param(["yogo.csv"], "yogo.csv", id="root_yogo"),
        pytest.param(["data/my.csv"], "data/my.csv", id="relative_path"),
        pytest.param(["resources/my.csv"], "resources/my.csv", id="resources_file_name"),
        pytest.param([], "yogo.csv", id="none"),
    ],
)
def test_migrate_env_when_relative_glossary(
    env_path: Path,
    tmp_path: Path,
    existing_files: list[str],
    expected_glossary: str,
) -> None:
    """相対の用語集は legacy と同じ順で .env のフォルダから解く（正常系）。"""
    from voice_paste.shared.env_migration import migrate_env

    # 準備
    env_path.write_text("YOGO_FILE=data/my.csv\n", encoding="utf-8")
    _write_files(tmp_path, existing_files)

    # 実行
    settings = migrate_env(env_path)

    # 検証
    assert settings.glossary_path == tmp_path / expected_glossary


def test_migrate_env_when_read_only(sample_env: Path, tmp_path: Path) -> None:
    """.env に触れない（正常系）。"""
    from voice_paste.shared.env_migration import migrate_env

    # 準備
    content_before = sample_env.read_bytes()
    mtime_before = sample_env.stat().st_mtime_ns
    environ_before = dict(os.environ)

    # 実行
    migrate_env(sample_env)

    # 検証（.env の中身・更新時刻・フォルダの中身・環境変数のどれも変わらない）
    assert sample_env.read_bytes() == content_before
    assert sample_env.stat().st_mtime_ns == mtime_before
    assert [path.name for path in tmp_path.iterdir()] == [".env"]
    assert dict(os.environ) == environ_before


def test_migrate_env_when_missing(env_path: Path) -> None:
    """.env が無い（異常系）。"""
    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.errors import SettingsError

    # 実行・検証
    with pytest.raises(SettingsError, match=r"\.env が無い"):
        migrate_env(env_path)


def test_migrate_env_when_unknown_engine(env_path: Path) -> None:
    """知らないエンジンを断る（異常系）。"""
    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.errors import SettingsError

    # 準備
    env_path.write_text("TRANSCRIPTION_ENGINE=azure\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match="TRANSCRIPTION_ENGINE"):
        migrate_env(env_path)


def test_migrate_env_when_invalid_number(env_path: Path) -> None:
    """数値に直せない値を元のキーで示す（異常系）。"""
    from voice_paste.shared.env_migration import migrate_env
    from voice_paste.shared.errors import SettingsError

    # 準備
    env_path.write_text("WHISPER_BEAM_SIZE=ten\n", encoding="utf-8")

    # 実行・検証
    with pytest.raises(SettingsError, match="WHISPER_BEAM_SIZE"):
        migrate_env(env_path)


@pytest.mark.parametrize(
    ("existing_files", "expected_glossary"),
    [
        pytest.param(["yogo.csv"], "yogo.csv", id="root_yogo"),
        pytest.param(["resources/yogo.csv"], "resources/yogo.csv", id="resources_yogo"),
    ],
)
def test_migrate_env_when_empty_glossary(
    env_path: Path,
    tmp_path: Path,
    existing_files: list[str],
    expected_glossary: str,
) -> None:
    """空の用語集は legacy と同じく直下の yogo.csv、無ければ resources/yogo.csv を指す（正常系）。"""
    from voice_paste.shared.env_migration import migrate_env

    # 準備
    env_path.write_text("YOGO_FILE=\n", encoding="utf-8")
    _write_files(tmp_path, existing_files)

    # 実行
    settings = migrate_env(env_path)

    # 検証
    assert settings.glossary_path == tmp_path / expected_glossary
