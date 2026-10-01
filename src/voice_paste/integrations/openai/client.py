"""OpenAI API での文字起こし。"""

from __future__ import annotations

import logging
from pathlib import Path

import openai
from openai import OpenAI

from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import OpenAISettings
from voice_paste.shared.types import ProgressFn

logger = logging.getLogger(__name__)

SEGMENT_MODEL: str = "whisper-1"
"""区間つきの応答（verbose_json）を返すモデル。"""

SEGMENT_RESPONSE_FORMAT: str = "verbose_json"
"""区間つきで受ける応答の形式。"""

PLAIN_RESPONSE_FORMAT: str = "json"
"""区間を返さないモデルで受ける応答の形式。"""


def transcribe_with_openai(
    audio_path: Path,
    on_progress: ProgressFn | None = None,
    *,
    settings: OpenAISettings,
    max_upload_bytes: int,
    request_timeout_sec: float,
    max_retries: int,
) -> list[str]:
    """OpenAI のエンジンの設定で録音を送り、区間ごとの文字を返す。"""
    # 1. API キーが空なら送らない
    api_key = settings.api_key.get_secret_value()
    if not api_key:
        raise EngineError("OpenAI の API キーが空")

    # 2. 録音のファイルの大きさが送れる上限を超えるなら送らない（費用の前に止める）
    size = audio_path.stat().st_size
    if size > max_upload_bytes:
        logger.warning(f"送れる大きさを超えたため送らなかった（{size} バイト・上限 {max_upload_bytes} バイト）")
        raise EngineError(f"録音が送れる大きさを超えた（{size} バイト・上限 {max_upload_bytes} バイト）")

    # 3. タイムアウトと再試行の回数を明示して作る（SDK の既定には頼らず、再試行は SDK の 1 層だけ）
    client = OpenAI(api_key=api_key, timeout=request_timeout_sec, max_retries=max_retries)

    # 4. 録音を送る。区間を返すのは whisper-1 だけで、ほかのモデルは区間なしの json で受ける
    response_format = (
        SEGMENT_RESPONSE_FORMAT if settings.model == SEGMENT_MODEL else PLAIN_RESPONSE_FORMAT
    )
    try:
        with audio_path.open("rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=settings.model,
                file=audio_file,
                language=settings.language,
                temperature=settings.temperature,
                response_format=response_format,
            )
    except openai.OpenAIError as error:
        # 届かない・タイムアウトした・エラーを返した（再試行を使い切った後）
        raise EngineError(f"OpenAI での文字起こしに失敗した（{error}）") from error

    # 5. 区間ごとに進みを知らせ、区間ごとの文字を返す。区間が無ければ全文を 1 つ返す
    segments = getattr(response, "segments", None) or []
    texts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            texts.append(text)
        if on_progress is not None:
            on_progress(segment.end, response.duration)
    if not texts:
        texts = [response.text.strip()]

    logger.info(f"OpenAI で文字に起こした（{settings.model}・区間 {len(segments)}）")
    return texts
