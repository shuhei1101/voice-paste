"""出力先の一覧。出力先を足すときに既存のモジュールで変えるのはここだけ。"""

from __future__ import annotations

from voice_paste.features.outputs.ai_chat import send_to_ai_chat
from voice_paste.features.outputs.callback import deliver_to_caller
from voice_paste.features.outputs.copy_only import copy_only
from voice_paste.features.outputs.paste_and_send import paste_and_send
from voice_paste.features.outputs.paste_only import paste_only
from voice_paste.features.outputs.types import OutputSpec

CALLBACK_OUTPUT_ID: str = "callback"
"""呼び出し元へ返す出力先の ID。"""

# 各 handler が受けるクリップボード・キー・ブラウザの操作と設定の値は、main.py が出力先の ID ごとに部分適用する
OUTPUTS: tuple[OutputSpec, ...] = (
    OutputSpec(
        id="paste_and_send",
        title="貼り付けて送信",
        handler=paste_and_send,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
    OutputSpec(
        id="paste_only",
        title="貼り付けのみ",
        handler=paste_only,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
    OutputSpec(
        id="copy_only",
        title="コピーのみ",
        handler=copy_only,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
    OutputSpec(
        id="ai_chat",
        title="AI チャットへ送る",
        handler=send_to_ai_chat,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
    OutputSpec(
        id=CALLBACK_OUTPUT_ID,
        title="呼び出し元へ返す",
        handler=deliver_to_caller,  # type: ignore[arg-type] 再送の関数などは main.py が部分適用する
        api_only=True,
    ),
)
"""登録した出力先。"""
