"""本物の文字起こしワーカーを動かしながら、faster-whisper の `transcribe` に渡された hotwords を記録する入口（E2E 用）。

常駐アプリがワーカーの代わりに `python -m tests.support.hotwords_probe_worker` で起動すると、
ワーカーの中で faster-whisper の `WhisperModel.transcribe` へ渡された hotwords が、環境変数 `PROBE_FILE_ENV` のファイルへ 1 行（JSON）ずつ追記される。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

PROBE_FILE_ENV = "VOICE_PASTE_E2E_HOTWORDS_FILE"
"""hotwords を追記するファイルの場所を渡す環境変数の名前。"""


def main() -> int:
    """`WhisperModel.transcribe` を、hotwords を記録してから本物を呼ぶものに替え、本物のワーカーを動かす。"""
    import faster_whisper

    from voice_paste.integrations.whisper import worker

    original = faster_whisper.WhisperModel.transcribe

    def probe(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 faster-whisper の引数をそのまま渡す
        """渡された hotwords（無ければ None）を記録して、本物の transcribe を呼ぶ。"""
        with open(os.environ[PROBE_FILE_ENV], "a", encoding="utf-8") as probe_file:
            probe_file.write(json.dumps(kwargs.get("hotwords"), ensure_ascii=False) + "\n")
        return original(self, *args, **kwargs)

    faster_whisper.WhisperModel.transcribe = probe
    return worker.main()


if __name__ == "__main__":
    sys.exit(main())
