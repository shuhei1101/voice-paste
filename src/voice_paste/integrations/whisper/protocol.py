"""常駐アプリと文字起こしワーカーが標準入出力でやり取りする 1 行の JSON。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerMessage(BaseModel):
    """標準入出力でやり取りする 1 行の JSON。type で種類を分ける。

    config（常駐 → ワーカー）/ ready（ワーカー → 常駐）/ transcribe（常駐 → ワーカー）/
    progress（区間の終わりの時刻）/ result（区間ごとの文字）/ error（理由）。
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["config", "ready", "transcribe", "progress", "result", "error"]
    payload: dict[str, Any] = Field(default_factory=dict)
    """種類ごとの中身。config: model・device・compute_type・cpu_threads・num_workers・log_dir /
    transcribe: audio_path・language・beam_size・best_of・temperature・vad_filter・vad_threshold・
    vad_min_speech_ms・vad_min_silence_ms・condition_on_previous_text・no_speech_threshold /
    progress: end・duration（秒）/ result: segments / error: message。"""

    def to_line(self) -> str:
        """改行で終わる 1 行の JSON にする。"""
        return self.model_dump_json() + "\n"

    @classmethod
    def from_line(cls, line: str) -> WorkerMessage:
        """1 行の JSON からメッセージを作る。JSON でない・知らない種類なら ValidationError を送出する。"""
        return cls.model_validate_json(line)
