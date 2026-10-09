"""入口と確定の操作で、出力先かカスタムプリセットを 1 つ選んで届ける。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from voice_paste.features.outputs.types import OutputSpec, PresetKindSpec
from voice_paste.shared.errors import UnknownOutputError
from voice_paste.shared.settings import Preset
from voice_paste.shared.types import Entry, TranscriptionOutcome

logger = logging.getLogger(__name__)


def deliver(
    entry: Entry | str,
    output_id: str | None,
    preset: Preset | None,
    callback_url: str | None,
    outcome: TranscriptionOutcome,
    *,
    enabled_ids: frozenset[str],
    outputs: Sequence[OutputSpec],
    preset_kinds: Sequence[PresetKindSpec],
) -> None:
    """入口が api なら呼び出し元へ返す出力先へ、それ以外は選んだプリセットか出力先へ届ける。"""
    # 1. 入口が api か
    if Entry(entry) == Entry.API:
        # api: 呼び出し元へ返す出力先を選び、返送先を宛先にする（設定のオン・オフ・プリセットによらない）
        spec = next((output for output in outputs if output.api_only), None)
        if spec is None:
            raise UnknownOutputError(f"出力先を選べません（入口: {entry}）")
        spec.handler(outcome, callback_url)
        logger.info(f"出力先へ渡した（{outcome.session_id}・出力先: {spec.id}）")
        return

    # 2. プリセットを選んでいれば、その種類の関数で届ける
    if preset is not None:
        kind_spec = next((kind for kind in preset_kinds if kind.kind == preset.kind), None)
        if kind_spec is None:
            raise UnknownOutputError(f"プリセットの種類を選べません（種類: {preset.kind}）")
        kind_spec.handler(outcome, preset)
        logger.info(
            f"出力先へ渡した（{outcome.session_id}・プリセットの種類: {preset.kind}・{preset.title}）"
        )
        return

    # 3. それ以外は、選んだ出力先の関数で届ける（API 専用のものと、設定でオフのものは選べない）
    spec = next(
        (
            output
            for output in outputs
            if output.id == output_id and not output.api_only and output.id in enabled_ids
        ),
        None,
    )
    if spec is None:
        raise UnknownOutputError(f"出力先を選べません（入口: {entry}・出力先: {output_id}）")
    spec.handler(outcome, None)
    logger.info(f"出力先へ渡した（{outcome.session_id}・出力先: {spec.id}）")
