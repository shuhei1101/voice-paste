"""入口と設定で出力先を 1 つ選んで届ける。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from voice_paste.features.outputs.types import OutputSpec
from voice_paste.shared.errors import UnknownOutputError
from voice_paste.shared.types import Entry, TranscriptionOutcome

logger = logging.getLogger(__name__)


def deliver(
    entry: Entry | str,
    output_id: str | None,
    output_target: str | None,
    callback_url: str | None,
    outcome: TranscriptionOutcome,
    *,
    enabled_ids: frozenset[str],
    outputs: Sequence[OutputSpec],
) -> None:
    """入口が api なら呼び出し元へ返す出力先へ、それ以外はセッションで選んだ出力先へ届ける。"""
    # 入口が api か
    if Entry(entry) == Entry.API:
        # api: 呼び出し元へ返す出力先を選び、返送先を宛先にする（設定のオン・オフによらない）
        spec = next((output for output in outputs if output.api_only), None)
        target = callback_url
    else:
        # それ以外: セッションで選んだ出力先を選び、選んだ出力先に固有の宛先を渡す（API 専用のものと、設定でオフのものは選べない）
        spec = next(
            (
                output
                for output in outputs
                if output.id == output_id and not output.api_only and output.id in enabled_ids
            ),
            None,
        )
        target = output_target
    if spec is None:
        raise UnknownOutputError(f"出力先を選べません（入口: {entry}・出力先: {output_id}）")

    # 選んだ出力先の関数で届ける
    spec.handler(outcome, target)
    logger.info(f"出力先へ渡した（{outcome.session_id}・出力先: {spec.id}）")
