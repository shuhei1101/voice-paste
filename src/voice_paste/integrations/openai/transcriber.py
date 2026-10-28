"""録音を OpenAI API の文字起こし（POST {base_url}/audio/transcriptions）へ httpx で送信する。"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import httpx
from pydantic import SecretStr

from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import OpenAISettings
from voice_paste.shared.types import ProgressFn

logger = logging.getLogger(__name__)

OPENAI_TIMEOUT_SEC: float = 600.0
"""1 回の送信で応答を待つ上限（秒）。"""

OPENAI_CONNECT_TIMEOUT_SEC: float = 5.0
"""接続を待つ上限（秒）。"""

OPENAI_MAX_RETRIES: int = 2
"""429・5xx・タイムアウト・接続できないときに送信し直す上限（最初の 1 回を含まない）。"""

OPENAI_RETRY_BASE_SEC: float = 0.5
"""送信し直しの待ちの基数（秒）。n 回目の待ちは 0 から基数 × 2^n の間の一様な乱数。"""

OPENAI_RETRY_MAX_SEC: float = 8.0
"""送信し直す前に待つ秒数の上限（Retry-After にもかける）。"""

OPENAI_MAX_AUDIO_BYTES: int = 26_209_484
"""送信する前に確かめる音声の大きさの上限（25 MB から要求の本文の固定の消費分を引いた値）。"""

OPENAI_AUDIO_SUFFIXES: frozenset[str] = frozenset(
    {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
)
"""OpenAI API が受ける音声の拡張子（小文字）。"""

OPENAI_MAX_AUDIO_MB: int = 25
"""音声の大きさの上限として利用者に示す MB 数。"""

HTTP_OK: int = 200
"""文字起こしに成功したときのステータス。"""

HTTP_TOO_MANY_REQUESTS: int = 429
"""レートリミットのステータス。"""

HTTP_SERVER_ERROR_MIN: int = 500
"""サーバーの失敗として送信し直すステータスの下限。"""

TRANSCRIPTIONS_PATH: str = "/audio/transcriptions"
"""ベース URL の後ろにつなぐ文字起こしのパス。"""


class OpenAITranscriber:
    """録音を OpenAI API で文字に起こす。API キーはヘッダーにだけ載せ、ログにも例外の文にも書かない。"""

    def __init__(
        self,
        *,
        settings: OpenAISettings,
        api_key: SecretStr,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """モデル・言語・ベース URL と API キーを受ける。sleep・uniform・transport はテストで差し替える。"""
        self._settings = settings
        self._api_key = api_key
        self._sleep = sleep
        self._uniform = uniform
        self._transport = transport

    def transcribe(
        self,
        audio_path: Path,
        *,
        on_progress: ProgressFn | None = None,
        hint: str | None = None,
    ) -> list[str]:
        """録音を送信し、起こした文字を 1 区間の並びで返す。起こした文字が空なら空の並びを返す。

        on_progress は受けるが呼ばない（OpenAI API は途中の進みを返さない）。
        """
        # 1. 送信する前に、音声の大きさと形式が受けられるかを手元で確かめる
        audio_size = self._check_audio(audio_path)

        # 2. 録音を送信する。一時的な失敗は回数の上限まで待って送信し直す
        url = f"{self._settings.base_url.rstrip('/')}{TRANSCRIPTIONS_PATH}"
        form = {
            "model": self._settings.model,
            "language": self._settings.language,
            "response_format": "json",
        }
        if hint is not None:
            # 手がかりがあるときだけ prompt を送信する
            form["prompt"] = hint
        files = {"file": (audio_path.name, audio_path.read_bytes())}
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        timeout = httpx.Timeout(OPENAI_TIMEOUT_SEC, connect=OPENAI_CONNECT_TIMEOUT_SEC)

        started = time.perf_counter()
        attempt = 0
        with httpx.Client(
            timeout=timeout, follow_redirects=False, transport=self._transport
        ) as client:
            while True:
                try:
                    response = client.post(url, headers=headers, data=form, files=files)
                except httpx.TransportError as error:
                    # タイムアウト・接続できない: 回数の上限までなら待って送信し直す
                    failure = type(error).__name__
                    retry_after = None
                else:
                    if response.status_code == HTTP_OK:
                        text = self._read_text(response)
                        logger.info(
                            f"OpenAI API で起こした（{self._settings.model}・{audio_size} バイト・"
                            f"{time.perf_counter() - started:.1f} 秒・{attempt + 1} 回）"
                        )
                        return [text] if text else []
                    failure = self._describe_failure(response)
                    if not self._is_retryable(response.status_code):
                        # 4xx（429 を除く）・リダイレクト: 送信し直さない
                        self._fail(failure)
                    retry_after = self._parse_retry_after(response.headers.get("Retry-After"))

                if attempt >= OPENAI_MAX_RETRIES:
                    # 回数の上限まで送信し直しても失敗した
                    self._fail(failure)
                wait_sec = self._wait_seconds(attempt, retry_after)
                logger.warning(f"OpenAI API へ送信し直す（{failure}・{wait_sec} 秒待つ）")
                self._sleep(wait_sec)
                attempt += 1

    @staticmethod
    def _check_audio(audio_path: Path) -> int:
        """音声の大きさと拡張子が OpenAI API の受けられるものかを確かめ、大きさを返す。外れれば EngineError。"""
        audio_size = audio_path.stat().st_size
        suffix = audio_path.suffix.lower()
        if audio_size > OPENAI_MAX_AUDIO_BYTES:
            logger.warning(f"OpenAI API へ送信しない音声（{audio_size} バイト・{suffix}）")
            raise EngineError(f"音声が OpenAI API の上限（{OPENAI_MAX_AUDIO_MB} MB）を超えています")
        if suffix not in OPENAI_AUDIO_SUFFIXES:
            logger.warning(f"OpenAI API へ送信しない音声（{audio_size} バイト・{suffix}）")
            raise EngineError(f"OpenAI API が受けられない形式です（{suffix}）")
        return audio_size

    @staticmethod
    def _read_text(response: httpx.Response) -> str:
        """成功の応答の JSON から、起こした文字の前後の空白を除いて返す。読めなければ EngineError。"""
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError):
            logger.error("OpenAI API の応答を読めなかった")
            raise EngineError("OpenAI API の応答を読めません") from None
        if not isinstance(text, str):
            logger.error("OpenAI API の応答の text が文字でない")
            raise EngineError("OpenAI API の応答を読めません")
        return text.strip()

    @staticmethod
    def _describe_failure(response: httpx.Response) -> str:
        """失敗の応答を、ステータスと JSON の error.type・error.code で表す（API キー・本文は含めない）。"""
        details = [str(response.status_code)]
        try:
            body = response.json()
        except ValueError:
            return details[0]
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            details.extend(str(error[name]) for name in ("type", "code") if error.get(name))
        return "・".join(details)

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        """レートリミットかサーバーの失敗のステータスか（送信し直す対象）。"""
        return status_code == HTTP_TOO_MANY_REQUESTS or status_code >= HTTP_SERVER_ERROR_MIN

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        """Retry-After の秒数を返す。無い・秒数でないときは None。"""
        if value is None:
            return None
        stripped = value.strip()
        if stripped.isascii() and stripped.isdigit():
            return float(stripped)
        return None

    def _wait_seconds(self, attempt: int, retry_after: float | None) -> float:
        """送信し直す前に待つ秒数。Retry-After があればそれ、無ければ指数バックオフのジッター。上限で頭打ちにする。"""
        if retry_after is None:
            retry_after = self._uniform(0, OPENAI_RETRY_BASE_SEC * 2**attempt)
        return min(retry_after, OPENAI_RETRY_MAX_SEC)

    @staticmethod
    def _fail(failure: str) -> NoReturn:
        """失敗をログに残し、EngineError を送出する。"""
        logger.error(f"OpenAI API の文字起こしに失敗した（{failure}）")
        raise EngineError(f"OpenAI API の文字起こしに失敗しました（{failure}）")
