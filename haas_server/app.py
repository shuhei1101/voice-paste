"""音声を文字に起こす API・準備の確認・停止の API と、Host・Origin の守りを持つ FastAPI の app。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol

import numpy as np
from fastapi import BackgroundTasks, FastAPI, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from haas_server.audio import AudioDecodeError, SAMPLE_RATE, decode_audio

logger = logging.getLogger(__name__)

SHORT_AUDIO_LIMIT_SEC: float = 30.0
"""これを超える音声は transcribe_longform で起こす。"""

PROBLEM_MEDIA_TYPE: str = "application/problem+json"
"""RFC 9457 のエラー応答の Content-Type。"""


class TranscribeFn(Protocol):
    """16 kHz モノラルの音声を起こす関数（haas_asr の transcribe・transcribe_longform）。"""

    def __call__(self, samples: np.ndarray, vocabulary: Any | None) -> str:
        """音声と Vocabulary（無ければ None）を受け、起こした文字を返す。"""
        ...


BuildVocabularyFn = Callable[[dict[str, list[str]]], Any]
"""表記 → 読みの一覧の対応から Vocabulary を作る関数（haas_asr.Vocabulary）。読みが無い語は空の一覧。"""


class VocabularyFormatError(Exception):
    """手がかりの形が合わない。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class HaasEngine:
    """create_app に渡す、モデルの関数と名前。"""

    model_name: str
    transcribe: TranscribeFn
    transcribe_longform: TranscribeFn
    build_vocabulary: BuildVocabularyFn


def problem_response(status: HTTPStatus, detail: str) -> JSONResponse:
    """RFC 9457 の problem+json の応答を作る。"""
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": "about:blank",
            "title": status.phrase,
            "status": status.value,
            "detail": detail,
        },
    )


def parse_vocabulary(raw: str | None) -> dict[str, list[str]]:
    """multipart の vocabulary（JSON の配列の文字列）を、表記 → 読みの一覧にする。形が合わなければ VocabularyFormatError。"""
    if raw is None:
        return {}
    try:
        items = json.loads(raw)
    except ValueError as error:
        raise VocabularyFormatError("手がかりが JSON ではない") from error
    if not isinstance(items, list):
        raise VocabularyFormatError("手がかりが配列ではない")
    words: dict[str, list[str]] = {}
    for item in items:
        written = item.get("written") if isinstance(item, dict) else None
        if not isinstance(written, str) or not written:
            raise VocabularyFormatError("手がかりの written が空か文字列ではない")
        reading = item.get("reading")
        readings = words.setdefault(written, [])
        if reading and reading not in readings:
            readings.append(reading)
    return words


def create_app(
    engine: HaasEngine, *, port: int, request_shutdown: Callable[[], None]
) -> FastAPI:
    """3 つの API と Host・Origin の守りを持つ FastAPI の app を作る。"""
    app = FastAPI()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    model_lock = threading.Lock()

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Host が 127.0.0.1 か localhost で、Origin が付いていない要求だけを通す。"""
        host = request.headers.get("host")
        origin = request.headers.get("origin")
        if host not in allowed_hosts or origin is not None:
            logger.warning(f"要求を断った（Host {host}・Origin {origin}）")
            return problem_response(HTTPStatus.FORBIDDEN, "この要求元からは受け付けない")
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, Any]:
        """モデルを読み込み終え、要求を受けられることを返す。"""
        return {"ok": True, "model": engine.model_name}

    @app.post("/shutdown", status_code=HTTPStatus.ACCEPTED)
    def shutdown(background: BackgroundTasks) -> None:
        """応答を返した後にサーバーを止める。起こしている要求は uvicorn が返し終えてから終わる。"""
        background.add_task(request_shutdown)

    @app.post("/transcriptions", response_model=None)
    def transcriptions(
        audio: UploadFile, vocabulary: str | None = Form(default=None)
    ) -> Response | dict[str, str]:
        """受けた音声を起こして返す。1 件ずつ起こす。"""
        # 1. 手がかりを読む
        try:
            words = parse_vocabulary(vocabulary)
        except VocabularyFormatError as error:
            logger.warning(f"手がかりの形が合わない（{error}）")
            return problem_response(HTTPStatus.BAD_REQUEST, str(error))

        # 2. 音声を復号する
        try:
            samples = decode_audio(audio.file.read())
        except AudioDecodeError as error:
            logger.warning(f"音声を復号できない（{error}）")
            return problem_response(HTTPStatus.BAD_REQUEST, str(error))

        # 3. 長さで起こし方を選んで起こす
        seconds = len(samples) / SAMPLE_RATE
        transcribe = (
            engine.transcribe if seconds <= SHORT_AUDIO_LIMIT_SEC else engine.transcribe_longform
        )
        started = time.perf_counter()
        try:
            with model_lock:
                built = engine.build_vocabulary(words) if words else None
                text = transcribe(samples, built)
        except Exception as error:  # noqa: BLE001 モデルの例外の種類を定めず、500 の理由にして次の要求を受ける
            logger.exception("文字起こしに失敗した")
            return problem_response(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

        # 4. 起こした文字を返す
        logger.info(f"起こした（音声 {seconds:.1f} 秒・{time.perf_counter() - started:.2f} 秒）")
        return {"text": text}

    return app
