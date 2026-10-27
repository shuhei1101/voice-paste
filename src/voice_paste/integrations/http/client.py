"""送信先へ httpx で JSON を POST する。"""

from __future__ import annotations

import functools
import ssl
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from voice_paste.integrations.http.types import PostResult
from voice_paste.shared.errors import DeliveryError


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    """httpx の SSL コンテキストを 1 回だけ作って使い回す（Client を作るたびに作ると約 145 ms かかる）。"""
    return httpx.create_ssl_context()


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After（秒数か HTTP の日付）を秒に換算する。無い・読めないときは None、過去の日付は 0 にそろえる。"""
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


def post_json(
    url: str,
    payload: dict[str, object],
    timeout_sec: float,
    headers: Mapping[str, str] | None = None,
) -> PostResult:
    """JSON を POST して、ステータスと Retry-After を返す。タイムアウトと接続できないことは DeliveryError にする。"""
    # 1. リダイレクトを追わずに headers を付けて POST する（許していないホストへ行かず、認証のヘッダーを他の先へ流さない）
    try:
        with httpx.Client(
            timeout=timeout_sec, follow_redirects=False, verify=_ssl_context()
        ) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.TransportError as error:
        # 例外の文には URL もヘッダーも書かず、例外の種類だけを残す（認証の値を出さない）
        raise DeliveryError(f"送信先へ送信できませんでした（{type(error).__name__}）") from error

    # 2〜3. Retry-After を秒に換算し、2xx 以外でも送出せずにステータスと一緒に返す
    return PostResult(
        status=response.status_code,
        retry_after_sec=_parse_retry_after(response.headers.get("Retry-After")),
    )
