"""設定で選んだエンジンで録音を文字に起こす。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from voice_paste.features.transcription.types import EngineFn
from voice_paste.shared.errors import EngineError, TranscriptionError
from voice_paste.shared.types import ProgressFn

logger = logging.getLogger(__name__)


def transcribe(
    audio_path: Path,
    on_progress: ProgressFn | None = None,
    *,
    engine: EngineFn,
    get_hint: Callable[[], str | None],
) -> str:
    """今の手がかりを添えてエンジンで録音を起こし、区間を改行でつなぐ。"""
    started = time.perf_counter()

    # 1. 今の設定の手がかりを引く（起こすたびに引くので、保存した設定が次の確定から効く）
    hint = get_hint()
    if hint is not None:
        logger.info(f"手がかりを渡す（{len(hint.encode('utf-8'))} バイト）")

    # 2. エンジンに録音と手がかりを渡して起こす
    try:
        segments = engine(audio_path, on_progress=on_progress, hint=hint)
    except EngineError as error:
        # エンジンの失敗: 理由を持たせた TranscriptionError にする
        raise TranscriptionError(f"文字起こしに失敗した（{error}）") from error

    # 3. 区間ごとに前後の空白を除き、空になった区間を除いて改行でつなぐ
    kept = [segment.strip() for segment in segments if segment.strip()]
    text = "\n".join(kept)
    logger.info(
        f"文字に起こした（区間 {len(kept)}・{len(text)} 文字・{time.perf_counter() - started:.1f} 秒）"
    )
    return text
