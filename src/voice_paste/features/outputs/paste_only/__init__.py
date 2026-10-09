"""出力先 paste_only（貼り付けのみ）。"""

from voice_paste.features.outputs.paste_only.service import inject_paste_only, paste_only
from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

__all__ = ["PasteOnlySettings", "inject_paste_only", "paste_only"]
