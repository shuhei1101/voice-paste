"""録音が受け取る関数の型（音量の操作・マイクの入力を開く・話し声の判定）。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import sounddevice as sd

type LowerVolumeFn = Callable[[float, float], float]
"""今の音量に対する割合（0.0〜1.0）と秒数を受け、下げ始めて下げる前の音量（0.0〜1.0）を返す関数。"""

type RestoreVolumeFn = Callable[[float, float], None]
"""戻す音量（0.0〜1.0）と秒数を受け、その音量へ戻し始める関数。"""

type OpenInputFn = Callable[[Callable[[np.ndarray], None]], sd.InputStream]
"""届いた音を受け取る関数を受け、マイクの入力を開いて始めたストリームを返す関数。"""

type SpeechProbabilityFn = Callable[[np.ndarray], float]
"""1 窓（VAD_WINDOW サンプル・float32）の話し声の確率（0.0〜1.0）を返す関数。前の窓からの状態を持ち越す。"""

type CreateSpeechDetectorFn = Callable[[], SpeechProbabilityFn]
"""状態を持たない新しい話し声の判定を作って返す関数（連続録音を始めるたびに呼ぶ）。"""
