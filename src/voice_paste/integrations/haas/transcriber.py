"""録音を Haas の文字起こしのサーバー（POST /transcriptions）へ httpx の multipart で送信する。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import HaasSettings, HintVocabularyWord
from voice_paste.shared.types import ProgressFn

logger = logging.getLogger(__name__)

HAAS_CONNECT_TIMEOUT_SEC: float = 3.0
"""接続を待つ秒数。"""

HAAS_RESPONSE_TIMEOUT_SEC: float = 180.0
"""応答を待つ秒数。"""

HTTP_OK: int = 200
"""文字起こしに成功したときのステータス。"""


class HaasTranscriber:
    """録音を Haas の文字起こしのサーバーへ送信し、起こした文字を返す。"""

    def __init__(
        self,
        *,
        port: int,
        get_vocabulary: Callable[[], list[HintVocabularyWord]],
        get_settings: Callable[[], HaasSettings],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """サーバーのポートと、送信するたびに表記と読みの組・調整の値を読む関数を受ける。transport はテストで差し替える。"""
        self._port = port
        self._get_vocabulary = get_vocabulary
        self._get_settings = get_settings
        self._transport = transport

    def transcribe(
        self,
        audio_path: Path,
        *,
        on_progress: ProgressFn | None = None,
        hint: str | None = None,
    ) -> list[str]:
        """録音を送信し、起こした文字を 1 区間の並びで返す。起こした文字が空なら空の並びを返す。

        on_progress は受けるが呼ばない（サーバーは途中の進みを返さない）。
        hint は受けるが使わない（読みを持たないため、_get_vocabulary の組を送信する）。
        """
        # 1. 語があれば、表記と読みの組を JSON にする
        words = self._get_vocabulary()
        form: dict[str, str] = _tuning_form(self._get_settings())
        if words:
            form["vocabulary"] = json.dumps(
                [{"written": word.written, "reading": word.reading} for word in words],
                ensure_ascii=False,
            )

        # 2. 録音と語を送信する
        audio = audio_path.read_bytes()
        timeout = httpx.Timeout(HAAS_RESPONSE_TIMEOUT_SEC, connect=HAAS_CONNECT_TIMEOUT_SEC)
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout, transport=self._transport) as client:
                response = client.post(
                    f"http://127.0.0.1:{self._port}/transcriptions",
                    files={"audio": (audio_path.name, audio)},
                    data=form,
                )
        except httpx.HTTPError as error:
            logger.error(f"Haas の文字起こしに失敗した（{type(error).__name__}）")
            raise EngineError(f"Haas のサーバーへ送信できない（{type(error).__name__}）") from error

        # 3. 成功なら起こした文字を返す。それ以外はステータスと detail を理由にする
        if response.status_code != HTTP_OK:
            reason = _describe_failure(response)
            logger.error(f"Haas の文字起こしに失敗した（{reason}）")
            raise EngineError(f"Haas の文字起こしに失敗した（{reason}）")
        text = str(response.json()["text"]).strip()
        logger.info(
            f"Haas で起こした（{len(audio)} バイト・{time.perf_counter() - started:.2f} 秒）"
        )
        return [text] if text else []


def _tuning_form(settings: HaasSettings) -> dict[str, str]:
    """要求ごとの調整の値を multipart の項目の文字列にする（guard は true / false）。"""
    return {
        "short_audio_limit_sec": str(settings.short_audio_limit_sec),
        "batch_size": str(settings.batch_size),
        "alpha": str(settings.alpha),
        "guard": "true" if settings.guard else "false",
        "chunk_sec": str(settings.chunk_sec),
        "search_sec": str(settings.search_sec),
        "window_sec": str(settings.window_sec),
        "separator": settings.separator,
    }


def _describe_failure(response: httpx.Response) -> str:
    """失敗の応答のステータスと problem+json の detail を 1 行にする。読めなければステータスだけを返す。"""
    try:
        detail = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return str(response.status_code)
    return f"{response.status_code}: {detail}"
