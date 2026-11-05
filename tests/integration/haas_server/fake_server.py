"""偽のモデルで haas_server.main を動かす、結合テスト用の別プロセスの入口。

引数: ポート・ログのファイル・作業フォルダ。
作業フォルダに started を書いてから、released が現れるまで待って決まった文字を返す。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import haas_server.main as main_module
from haas_server.app import HaasEngine
from tests.integration.haas_server.helpers import FAKE_TEXT, MODEL_NAME

POLL_SEC = 0.01


def _run(port: str, log_file: str, work_dir: str) -> None:
    """読み込みを偽物に差し替えて、サーバーの入口を動かす。"""
    work = Path(work_dir)

    def transcribe(_samples: Any, _vocabulary: Any | None) -> str:
        """放されるまで待ってから、決まった文字を返す。"""
        (work / "started").touch()
        while not (work / "released").exists():
            time.sleep(POLL_SEC)
        return FAKE_TEXT

    main_module.LOG_FILE = Path(log_file)
    main_module.load_engine = lambda: HaasEngine(
        model_name=MODEL_NAME,
        transcribe=transcribe,
        transcribe_longform=transcribe,
        build_vocabulary=lambda words: words,
    )
    main_module.main([port])


if __name__ == "__main__":
    _run(*sys.argv[1:])
