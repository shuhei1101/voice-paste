"""出力先の機能。"""

from voice_paste.features.outputs.callback import is_callback_allowed
from voice_paste.features.outputs.registry import OUTPUTS, PRESET_KINDS
from voice_paste.features.outputs.service import deliver
from voice_paste.features.outputs.types import (
    InjectFn,
    OutputDeps,
    OutputFn,
    OutputSpec,
    PresetFn,
    PresetKindSpec,
    ResultPayload,
)

__all__ = [
    "OUTPUTS",
    "PRESET_KINDS",
    "InjectFn",
    "OutputDeps",
    "OutputFn",
    "OutputSpec",
    "PresetFn",
    "PresetKindSpec",
    "ResultPayload",
    "deliver",
    "is_callback_allowed",
]
