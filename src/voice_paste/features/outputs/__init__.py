"""出力先の機能。"""

from voice_paste.features.outputs.callback import is_callback_allowed
from voice_paste.features.outputs.registry import OUTPUTS
from voice_paste.features.outputs.service import deliver
from voice_paste.features.outputs.types import OutputFn, OutputSpec

__all__ = ["OUTPUTS", "OutputFn", "OutputSpec", "deliver", "is_callback_allowed"]
