"""出力先 callback（呼び出し元へ返す）。"""

from voice_paste.features.outputs.callback.service import deliver_to_caller, is_callback_allowed

__all__ = ["deliver_to_caller", "is_callback_allowed"]
