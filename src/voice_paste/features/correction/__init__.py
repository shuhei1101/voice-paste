"""用語集による文字の補正の機能。"""

from voice_paste.features.correction.service import (
    DEFAULT_GLOSSARY_FILE_NAME,
    DEFAULT_GLOSSARY_PRESET_NAME,
    apply_glossary,
    list_preset_glossaries,
    load_glossary,
    next_glossary_path,
    pick_glossary_preset,
    read_glossary_rows,
    resolve_glossaries,
    resolve_glossary_presets,
    save_glossary,
    strip_edge_phrases,
)

__all__ = [
    "DEFAULT_GLOSSARY_FILE_NAME",
    "DEFAULT_GLOSSARY_PRESET_NAME",
    "apply_glossary",
    "list_preset_glossaries",
    "load_glossary",
    "next_glossary_path",
    "pick_glossary_preset",
    "read_glossary_rows",
    "resolve_glossaries",
    "resolve_glossary_presets",
    "save_glossary",
    "strip_edge_phrases",
]
