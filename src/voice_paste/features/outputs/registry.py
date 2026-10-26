"""出力先・プリセットの種類の一覧。追加するときに既存のモジュールで変えるのはここだけ。"""

from __future__ import annotations

from voice_paste.features.outputs.browser import send_to_browser
from voice_paste.features.outputs.callback import deliver_to_caller, inject_callback
from voice_paste.features.outputs.copy_only import CopyOnlySettings, copy_only, inject_copy_only
from voice_paste.features.outputs.endpoint import deliver_to_endpoint
from voice_paste.features.outputs.paste_and_send import (
    PasteAndSendSettings,
    inject_paste_and_send,
    paste_and_send,
)
from voice_paste.features.outputs.paste_only import PasteOnlySettings, inject_paste_only, paste_only
from voice_paste.features.outputs.types import OutputSpec, PresetKindSpec

CALLBACK_OUTPUT_ID: str = "callback"
"""呼び出し元へ返す出力先の ID。"""

# 各 handler が受けるクリップボード・キー・ブラウザの操作と設定の値は、各出力先の inject が OutputDeps から選び、main.py が部分適用する
OUTPUTS: tuple[OutputSpec, ...] = (
    OutputSpec(
        id="paste_and_send",
        title="貼り付けて送信",
        handler=paste_and_send,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
        settings_model=PasteAndSendSettings,
        inject=inject_paste_and_send,
    ),
    OutputSpec(
        id="paste_only",
        title="貼り付けのみ",
        handler=paste_only,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
        settings_model=PasteOnlySettings,
        inject=inject_paste_only,
    ),
    OutputSpec(
        id="copy_only",
        title="コピーのみ",
        handler=copy_only,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
        settings_model=CopyOnlySettings,
        inject=inject_copy_only,
    ),
    OutputSpec(
        id=CALLBACK_OUTPUT_ID,
        title="呼び出し元へ返す",
        handler=deliver_to_caller,  # type: ignore[arg-type] 再送の関数などは main.py が部分適用する
        inject=inject_callback,
        api_only=True,
    ),
)
"""登録した出力先。"""

# 各 handler が受けるクリップボード・キー・ブラウザ・HTTP の操作と設定の値は、main.py が種類ごとに部分適用する
PRESET_KINDS: tuple[PresetKindSpec, ...] = (
    PresetKindSpec(
        kind="browser",
        title="ブラウザ添付",
        handler=send_to_browser,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
    PresetKindSpec(
        kind="endpoint",
        title="エンドポイントへ送信",
        handler=deliver_to_endpoint,  # type: ignore[arg-type] 注入する関数は main.py が部分適用する
    ),
)
"""登録したカスタムプリセットの種類。"""
