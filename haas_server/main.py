"""Haas-ja-v1.0 のモデルを読み込み、127.0.0.1 で待ち受けるサーバーの入口。"""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn

from haas_server.app import HaasEngine, create_app

logger = logging.getLogger(__name__)

HAAS_MODEL_NAME: str = "third-intelligence/Haas-ja-v1.0"
"""Hugging Face Hub から取得するモデル。"""

LONGFORM_BATCH_SIZE: int = 64
"""transcribe_longform に渡すバッチの大きさ（PoC で約 176 秒の音声を 0.18 秒で起こした値）。"""

LOG_FILE: Path = Path.home() / ".local" / "state" / "voice-paste" / "haas_server.log"
"""ログの置き場所。起動の前から動いているサーバーでは常駐アプリが標準エラーを受けられないため、WSL の中のファイルにする。"""

LOG_MAX_BYTES: int = 1_000_000
"""ログを切り替える大きさ。"""

LOG_BACKUP_COUNT: int = 3
"""残すログの世代の数。"""


def load_engine() -> HaasEngine:
    """haas_asr を import してモデルを読み込み、HaasEngine にする。"""
    import haas_asr  # noqa: PLC0415 Windows の環境とテストでは入っていないため、ここでだけ読む

    started = time.perf_counter()
    model = haas_asr.load_model(HAAS_MODEL_NAME)
    logger.info(f"モデルを読み込んだ（{time.perf_counter() - started:.1f} 秒）")

    def transcribe(samples: Any, vocabulary: Any | None) -> str:
        """30 秒以下の音声を起こす。"""
        return haas_asr.transcribe(model, [samples], vocabulary=vocabulary)[0]

    def transcribe_longform(samples: Any, vocabulary: Any | None) -> str:
        """30 秒を超える音声を静かな箇所で区切って起こす。"""
        return haas_asr.transcribe_longform(
            model, samples, batch_size=LONGFORM_BATCH_SIZE, vocabulary=vocabulary
        )

    return HaasEngine(
        model_name=HAAS_MODEL_NAME,
        transcribe=transcribe,
        transcribe_longform=transcribe_longform,
        build_vocabulary=haas_asr.Vocabulary,
    )


def _setup_logging() -> None:
    """ログを WSL の中のファイルへ書くようにする。"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main(argv: list[str]) -> None:
    """ログを設定し、モデルを読み込んでから 127.0.0.1 で待ち受ける。サーバーが止まると戻る。"""
    port = int(argv[0])
    _setup_logging()
    # 読み込みの間は待ち受けない（/health の応答が準備できたことを表す）
    engine = load_engine()
    holder: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        """サーバーを止める。"""
        holder["server"].should_exit = True

    app = create_app(engine, port=port, request_shutdown=request_shutdown)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    holder["server"] = server
    server.run()


if __name__ == "__main__":
    main(sys.argv[1:])
