"""用語集による文字の補正の機能。"""

from voice_paste.features.correction.service import (
    DEFAULT_GLOSSARY_FILE_NAME,
    apply_glossary,
    load_glossary,
    next_glossary_path,
    pick_active_glossary,
    read_glossary_rows,
    resolve_glossaries,
    save_glossary,
)

__all__ = [
    "DEFAULT_GLOSSARY_FILE_NAME",
    "apply_glossary",
    "load_glossary",
    "next_glossary_path",
    "pick_active_glossary",
    "read_glossary_rows",
    "resolve_glossaries",
    "save_glossary",
]
