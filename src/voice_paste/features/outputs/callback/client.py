"""返送先へ httpx で JSON を POST する。"""

from __future__ import annotations

import functools
import ssl
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from voice_paste.features.outputs.callback.types import PostResult
from voice_paste.shared.errors import DeliveryError


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    """httpx の SSL コンテキストを 1 回だけ作って使い回す（Client を作るたびに作ると約 145 ms かかる）。"""
    return httpx.create_ssl_context()


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After（秒数か HTTP の日付）を秒に直す。無い・読めないときは None、過去の日付は 0 にそろえる。"""
    # 1. ヘッダが無ければ None
    if value is None:
        return None

    # 2. 秒数はそのまま使う
    stripped = value.strip()
    if stripped.isascii() and stripped.isdigit():
        return float(stripped)

    # 3. HTTP の日付は今の時刻からの差にする（過去は 0）。読めなければ None
    try:
        moment = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


def post_json(url: str, payload: dict[str, object], timeout_sec: float) -> PostResult:
    """JSON を POST して、ステータスと Retry-After を返す。タイムアウトと接続できないことは DeliveryError にする。"""
    # 1. リダイレクトを追わずに POST する（許していないホストへ流れないため）
    try:
        with httpx.Client(
            timeout=timeout_sec, follow_redirects=False, verify=_ssl_context()
        ) as client:
            response = client.post(url, json=payload)
    except httpx.TransportError as error:
        raise DeliveryError(f"返送先へ送れませんでした（{error!r}）") from error

    # 2〜3. Retry-After を秒に直し、2xx 以外でも送出せずにステータスと一緒に返す
    return PostResult(
        status=response.status_code,
        retry_after_sec=_parse_retry_after(response.headers.get("Retry-After")),
    )
