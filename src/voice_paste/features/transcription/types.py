"""文字起こしのエンジンの種類と関数型。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from voice_paste.shared.types import ProgressFn


class EngineName(StrEnum):
    """設定で選ぶ文字起こしのエンジン。"""

    LOCAL_WHISPER = "local_whisper"
    """文字起こしワーカーの子プロセスで起こす。"""

    OPENAI = "openai"
    """OpenAI API で起こす。"""


class EngineFn(Protocol):
    """1 つのエンジンで録音を起こす関数。エンジンを足すときはこの型の実装を足して main.py で登録する。"""

    def __call__(
        self, audio_path: Path, *, on_progress: ProgressFn | None = None
    ) -> list[str]:
        """録音の WAV を起こして区間ごとの文字を返す。"""
        ...
