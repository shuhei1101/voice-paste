"""エンドポイントへ送信する。選んだプリセットの URL へ、送信する内容を 1 回 POST する。再送しない。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from http import HTTPStatus

from voice_paste.features.outputs.types import ResultPayload
from voice_paste.integrations.http.types import PostJsonFn
from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.settings import EndpointPreset, Preset
from voice_paste.shared.types import TranscriptionOutcome

logger = logging.getLogger(__name__)

AUTHORIZATION_HEADER: str = "Authorization"
"""プリセットの authorization の値を入れるヘッダー名。"""


def deliver_to_endpoint(
    outcome: TranscriptionOutcome,
    preset: Preset,
    *,
    post: PostJsonFn,
    get_timeout_sec: Callable[[], float],
) -> None:
    """送信する内容を、プリセットの URL へ 1 回だけ POST する。届かなければ再送せず DeliveryError。"""
    # 1. エンドポイントへ送信のプリセットでなければ断る（種類と関数の取り違え）
    if not isinstance(preset, EndpointPreset):
        raise DeliveryError(f"エンドポイントへ送信のプリセットではありません（種類: {preset.kind}）")

    # 2. 送信する内容と、Authorization の値が空でなければそのヘッダーを作る（値はログにも例外の文にも書かない）
    payload = ResultPayload.from_outcome(outcome).model_dump()
    headers = {AUTHORIZATION_HEADER: preset.authorization} if preset.authorization else {}

    # 3. 1 回だけ送る（タイムアウト・接続できないは DeliveryError のまま伝え、送り直さない）
    result = post(preset.url, payload, get_timeout_sec(), headers)

    # 4. 2xx なら終える。2xx 以外（3xx を含む）は送り直さず断る
    if not HTTPStatus.OK <= result.status < HTTPStatus.MULTIPLE_CHOICES:
        raise DeliveryError(
            f"エンドポイントへ届けられませんでした（{preset.title}・ステータス {result.status}）"
        )
    logger.info(
        f"エンドポイントへ届けた（{outcome.session_id}・{preset.title}・ステータス {result.status}）"
    )
