"""音声を文字に起こす API・準備の確認・停止の API と、Host・Origin の守りを持つ FastAPI の app。"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol

import numpy as np
from fastapi import BackgroundTasks, FastAPI, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from haas_server.audio import AudioDecodeError, SAMPLE_RATE, decode_audio

logger = logging.getLogger(__name__)

TUNING_FLOAT_RANGES: dict[str, tuple[float, float]] = {
    "short_audio_limit_sec": (1.0, 60.0),
    "alpha": (0.0, 10.0),
    "chunk_sec": (1.0, 60.0),
    "search_sec": (0.0, 10.0),
    "window_sec": (0.01, 1.0),
}
"""小数の調整の値ごとの下限と上限（両端を含む）。chunk_sec は 0 だと区切りが進まず、window_sec は 16 kHz で 1 サンプル以上の窓にする。"""

BATCH_SIZE_RANGE: tuple[int, int] = (1, 256)
"""batch_size の下限と上限（両端を含む）。"""

SEPARATOR_MAX_LENGTH: int = 16
"""separator の文字数の上限。"""

GUARD_VALUES: dict[str, bool] = {"true": True, "false": False}
"""guard として受ける文字列。"""

PROBLEM_MEDIA_TYPE: str = "application/problem+json"
"""RFC 9457 のエラー応答の Content-Type。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class TranscribeOptions:
    """POST /transcriptions の調整の値を検証した後の値。既定値はインターフェース定義の default と同じ。"""

    short_audio_limit_sec: float = 30.0
    batch_size: int = 64
    alpha: float = 2.0
    guard: bool = True
    chunk_sec: float = 30.0
    search_sec: float = 2.0
    window_sec: float = 0.1
    separator: str = ""


class TranscribeFn(Protocol):
    """16 kHz モノラルの音声を起こす関数（haas_asr の transcribe・transcribe_longform）。"""

    def __call__(
        self, samples: np.ndarray, vocabulary: Any | None, options: TranscribeOptions
    ) -> str:
        """音声と Vocabulary（無ければ None）と調整の値を受け、起こした文字を返す。"""
        ...


class BuildVocabularyFn(Protocol):
    """表記 → 読みの一覧の対応と手がかりの強さから Vocabulary を作る関数（haas_asr.Vocabulary）。"""

    def __call__(self, words: dict[str, list[str]], alpha: float) -> Any:
        """読みが無い語は空の一覧で受ける。"""
        ...


class VocabularyFormatError(Exception):
    """手がかりの形が合わない。"""


class TuningValueError(Exception):
    """要求の調整の値が範囲の外か型が合わない。"""

    def __init__(self, field: str, reason: str) -> None:
        """合わない項目の名前と理由を受ける。"""
        super().__init__(f"{field}: {reason}")
        self.field = field


@dataclass(frozen=True, slots=True, kw_only=True)
class HaasEngine:
    """create_app に渡す、モデルの関数と、起動の引数で受けたモデル・計算の精度・装置。"""

    model_name: str
    dtype: str
    device: str
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


def _parse_float(field: str, raw: str) -> float:
    """小数の項目を読み、範囲の中かを確かめる。外れれば TuningValueError。"""
    try:
        value = float(raw)
    except ValueError as error:
        raise TuningValueError(field, "数値ではない") from error
    low, high = TUNING_FLOAT_RANGES[field]
    if not math.isfinite(value) or not low <= value <= high:
        raise TuningValueError(field, f"{low} 以上 {high} 以下ではない")
    return value


def parse_tuning(fields: Mapping[str, str | None]) -> TranscribeOptions:
    """multipart の項目の文字列から調整の値を読み、範囲を確かめて TranscribeOptions にする。無い項目は既定値。"""
    values: dict[str, Any] = {}
    for field in TUNING_FLOAT_RANGES:
        raw = fields.get(field)
        if raw is not None:
            values[field] = _parse_float(field, raw)

    raw_batch = fields.get("batch_size")
    if raw_batch is not None:
        try:
            batch_size = int(raw_batch)
        except ValueError as error:
            raise TuningValueError("batch_size", "整数ではない") from error
        low, high = BATCH_SIZE_RANGE
        if not low <= batch_size <= high:
            raise TuningValueError("batch_size", f"{low} 以上 {high} 以下ではない")
        values["batch_size"] = batch_size

    raw_guard = fields.get("guard")
    if raw_guard is not None:
        if raw_guard not in GUARD_VALUES:
            raise TuningValueError("guard", "true でも false でもない")
        values["guard"] = GUARD_VALUES[raw_guard]

    separator = fields.get("separator")
    if separator is not None:
        if len(separator) > SEPARATOR_MAX_LENGTH:
            raise TuningValueError("separator", f"{SEPARATOR_MAX_LENGTH} 文字を超える")
        values["separator"] = separator

    return TranscribeOptions(**values)


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
        return {
            "ok": True,
            "model": engine.model_name,
            "dtype": engine.dtype,
            "device": engine.device,
        }

    @app.post("/shutdown", status_code=HTTPStatus.ACCEPTED)
    def shutdown(background: BackgroundTasks) -> None:
        """応答を返した後にサーバーを止める。起こしている要求は uvicorn が返し終えてから終わる。"""
        background.add_task(request_shutdown)

    @app.post("/transcriptions", response_model=None)
    def transcriptions(
        audio: UploadFile,
        vocabulary: str | None = Form(default=None),
        short_audio_limit_sec: str | None = Form(default=None),
        batch_size: str | None = Form(default=None),
        alpha: str | None = Form(default=None),
        guard: str | None = Form(default=None),
        chunk_sec: str | None = Form(default=None),
        search_sec: str | None = Form(default=None),
        window_sec: str | None = Form(default=None),
        separator: str | None = Form(default=None),
    ) -> Response | dict[str, str]:
        """受けた音声を起こして返す。1 件ずつ起こす。"""
        # 1. 手がかりを読む
        try:
            words = parse_vocabulary(vocabulary)
        except VocabularyFormatError as error:
            logger.warning(f"手がかりの形が合わない（{error}）")
            return problem_response(HTTPStatus.BAD_REQUEST, str(error))

        # 2. 調整の値を読む（bool・数値の型で受けると FastAPI が yes を通し、型の合わない値を 422 にするため文字列で受ける）
        try:
            options = parse_tuning(
                {
                    "short_audio_limit_sec": short_audio_limit_sec,
                    "batch_size": batch_size,
                    "alpha": alpha,
                    "guard": guard,
                    "chunk_sec": chunk_sec,
                    "search_sec": search_sec,
                    "window_sec": window_sec,
                    "separator": separator,
                }
            )
        except TuningValueError as error:
            logger.warning(f"調整の値が合わない（{error}）")
            return problem_response(HTTPStatus.BAD_REQUEST, str(error))

        # 3. 音声を復号する
        try:
            samples = decode_audio(audio.file.read())
        except AudioDecodeError as error:
            logger.warning(f"音声を復号できない（{error}）")
            return problem_response(HTTPStatus.BAD_REQUEST, str(error))

        # 4. 長さで起こし方を選んで起こす
        seconds = len(samples) / SAMPLE_RATE
        transcribe = (
            engine.transcribe
            if seconds <= options.short_audio_limit_sec
            else engine.transcribe_longform
        )
        started = time.perf_counter()
        try:
            with model_lock:
                built = engine.build_vocabulary(words, options.alpha) if words else None
                text = transcribe(samples, built, options)
        except Exception as error:  # noqa: BLE001 モデルの例外の種類を定めず、500 の理由にして次の要求を受ける
            logger.exception("文字起こしに失敗した")
            return problem_response(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

        # 5. 起こした文字を返す
        logger.info(f"起こした（音声 {seconds:.1f} 秒・{time.perf_counter() - started:.2f} 秒）")
        return {"text": text}

    return app
