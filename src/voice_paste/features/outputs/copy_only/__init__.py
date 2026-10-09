"""出力先 copy_only（コピーのみ）。"""

from voice_paste.features.outputs.copy_only.service import copy_only, inject_copy_only
from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings

__all__ = ["CopyOnlySettings", "copy_only", "inject_copy_only"]
