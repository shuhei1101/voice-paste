"""用語集による文字の補正の機能。"""

from voice_paste.features.correction.service import apply_glossary, load_glossary
from voice_paste.features.correction.types import GlossaryEntry

__all__ = ["GlossaryEntry", "apply_glossary", "load_glossary"]
