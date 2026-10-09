"""返送先の確かめと、起こした文字の呼び出し元への返送（再送つき）。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from functools import partial
from http import HTTPStatus
from urllib.parse import urlparse

from voice_paste.features.outputs.types import OutputDeps, ResultPayload
from voice_paste.integrations.http.types import PostResult
from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
"""設定によらず返送を許すホスト。"""

RETRYABLE_STATUSES: frozenset[int] = frozenset(
    {HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS}
)
"""4xx のうち、送り直せば届くことがあるステータス。"""

BACKOFF_FACTOR: int = 2
"""再送の間隔を回ごとに何倍にするか。"""

CALLBACK_TIMEOUT_SEC: float = 1.5
"""返送の 1 回の POST のタイムアウト。非機能要件の返送のタイムアウトと再送の決定値。"""

CALLBACK_RETRY_COUNT: int = 3
"""返送を最初の 1 回の後に再送する回数。非機能要件の返送のタイムアウトと再送の決定値。"""

CALLBACK_RETRY_BASE_SEC: float = 1.0
"""返送の再送の間隔の基数（回ごとに 2 倍にし、フルジッターをかける）。非機能要件の決定値。"""


def is_callback_allowed(url: str, allowed_hosts: frozenset[str]) -> bool:
    """返送先のホストが loopback か、設定で許可したホストかを返す。"""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    return host is not None and (host in LOOPBACK_HOSTS or host in allowed_hosts)


def _is_retryable(status: int) -> bool:
    """送り直せば届くことがあるステータス（5xx・408・429）か。"""
    return status >= HTTPStatus.INTERNAL_SERVER_ERROR or status in RETRYABLE_STATUSES


def deliver_to_caller(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    post: Callable[[str, dict[str, object]], PostResult],
    allowed_hosts: frozenset[str],
    retry_count: int,
    retry_base_sec: float,
    sleep: Callable[[float], None],
    jitter: Callable[[float], float],
) -> None:
    """返送先へ結果を POST し、届かなければ決めた回数まで再送する。届かなくてもログに書いて終える。"""
    # 1. 返送先が許されるかをもう一度確かめる（開始の後に設定が変わったかもしれない）
    if target is None or not is_callback_allowed(target, allowed_hosts):
        raise DeliveryError("返送先が許されていません")

    # 2. 返送の中身を作り、1 + 再送回数まで POST する
    payload = ResultPayload.from_outcome(outcome).model_dump()
    # 返送の間はセッションが残り次の開始を断るため、待ちはこの上限に収める
    max_wait_sec = retry_base_sec * BACKOFF_FACTOR ** (retry_count - 1)
    reason = ""
    for attempt in range(1, retry_count + 2):
        # 2-1. POST する
        retry_after_sec: float | None = None
        try:
            result = post(target, payload)
        except DeliveryError as error:
            # タイムアウト・接続できない: 送り直せる
            retryable = True
            reason = str(error)
        else:
            if HTTPStatus.OK <= result.status < HTTPStatus.MULTIPLE_CHOICES:
                logger.info(
                    f"返送先へ届けた（{outcome.session_id}・{outcome.result}・{attempt} 回目）"
                )
                return
            retryable = _is_retryable(result.status)
            reason = f"ステータス {result.status}"
            retry_after_sec = result.retry_after_sec

        # 2-2. 送り直しても変わらない応答か、次の回が無ければ打ち切る
        if not retryable or attempt > retry_count:
            break

        # 2-3. 待ちを決める。Retry-After があればその秒数（上限を超えるなら待たずに打ち切る）、無ければ指数バックオフとフルジッター
        if retry_after_sec is not None:
            if retry_after_sec > max_wait_sec:
                break
            wait_sec = retry_after_sec
        else:
            wait_sec = jitter(retry_base_sec * BACKOFF_FACTOR ** (attempt - 1))
        logger.warning(f"返送に失敗した（{outcome.session_id}・{attempt} 回目・{reason}）")
        sleep(wait_sec)

    # 3. 届かなかったらログに書いて終える（送出しない。履歴は残っている）
    logger.error(f"返送先に届かなかった（{outcome.session_id}・最後の理由: {reason}）")


def inject_callback(deps: OutputDeps) -> Mapping[str, object]:
    """deliver_to_caller に部分適用する post・allowed_hosts・retry_count・retry_base_sec・sleep・jitter を返す。"""
    return {
        # 返送のタイムアウトを部分適用した post_json
        "post": partial(deps.post, timeout_sec=CALLBACK_TIMEOUT_SEC),
        # 呼ぶ時点の設定の許可ホスト
        "allowed_hosts": frozenset(deps.get_settings().api.allowed_callback_hosts),
        "retry_count": CALLBACK_RETRY_COUNT,
        "retry_base_sec": CALLBACK_RETRY_BASE_SEC,
        "sleep": deps.sleep,
        "jitter": deps.jitter,
    }
