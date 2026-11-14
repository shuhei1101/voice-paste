"""Haas-ja-v1.0 のモデルを読み込み、127.0.0.1 で待ち受けるサーバーの入口。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal, cast

import uvicorn

from haas_server.app import HaasEngine, TranscribeOptions, create_app

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME: str = "third-intelligence/Haas-ja-v1.0"
"""起動の引数にモデルが無いときに Hugging Face Hub から取得するモデル。"""

DEFAULT_DTYPE: str = "auto"
"""起動の引数に計算の精度が無いときの値（haas_asr.load_model の既定と同じ）。"""

DEFAULT_DEVICE: str = "cuda"
"""起動の引数に装置が無いときの値（haas_asr.load_model の既定と同じ）。"""

DTYPE_NAMES: tuple[str, ...] = ("auto", "bfloat16", "float16", "float32")
"""起動の引数で受ける計算の精度。auto はそのまま、ほかは同じ名前の torch の型にして load_model に渡す（load_model は auto 以外の文字列を受けない）。"""

AUTO_DTYPE: str = "auto"
"""load_model にそのまま渡す計算の精度。"""

LOG_FILE: Path = Path.home() / ".local" / "state" / "voice-paste" / "haas_server.log"
"""ログの置き場所。起動の前から動いているサーバーでは常駐アプリが標準エラーを受けられないため、WSL の中のファイルにする。"""

LOG_MAX_BYTES: int = 1_000_000
"""ログを切り替える大きさ。"""

LOG_BACKUP_COUNT: int = 3
"""残すログの世代の数。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerArgs:
    """start.sh から受けたポート・モデル・計算の精度・装置。"""

    port: int
    model: str
    dtype: Literal["auto", "bfloat16", "float16", "float32"]
    device: str


def parse_args(argv: list[str]) -> ServerArgs:
    """位置の引数（ポート・モデル・計算の精度・装置）を読む。読めなければ argparse が終了コード 2 で終える。"""
    parser = argparse.ArgumentParser(prog="haas_server")
    parser.add_argument("port", type=int)
    parser.add_argument("model", nargs="?", default=DEFAULT_MODEL_NAME)
    parser.add_argument("dtype", nargs="?", default=DEFAULT_DTYPE, choices=DTYPE_NAMES)
    parser.add_argument("device", nargs="?", default=DEFAULT_DEVICE)
    namespace = parser.parse_args(argv)
    return ServerArgs(
        port=namespace.port,
        model=namespace.model,
        dtype=cast("Literal['auto', 'bfloat16', 'float16', 'float32']", namespace.dtype),
        device=namespace.device,
    )


def load_engine(args: ServerArgs) -> HaasEngine:
    """haas_asr を import して起動の引数のモデルを読み込み、HaasEngine にする。"""
    import haas_asr  # noqa: PLC0415 Windows の環境とテストでは入っていないため、ここでだけ読む
    import torch  # noqa: PLC0415 同上

    started = time.perf_counter()
    dtype: Any = args.dtype if args.dtype == AUTO_DTYPE else getattr(torch, args.dtype)
    model = haas_asr.load_model(args.model, device=args.device, dtype=dtype)
    logger.info(
        f"モデルを読み込んだ（{args.model}・{args.dtype}・{args.device}・"
        f"{time.perf_counter() - started:.1f} 秒）"
    )

    def transcribe(samples: Any, vocabulary: Any | None, options: TranscribeOptions) -> str:
        """上限の長さ以下の音声を一度に起こす。"""
        return haas_asr.transcribe(
            model,
            [samples],
            batch_size=options.batch_size,
            vocabulary=vocabulary,
            guard=options.guard,
        )[0]

    def transcribe_longform(
        samples: Any, vocabulary: Any | None, options: TranscribeOptions
    ) -> str:
        """上限の長さを超える音声を静かな箇所で区切って起こす。"""
        return haas_asr.transcribe_longform(
            model,
            samples,
            batch_size=options.batch_size,
            separator=options.separator,
            vocabulary=vocabulary,
            guard=options.guard,
            chunk_seconds=options.chunk_sec,
            search_seconds=options.search_sec,
            window_seconds=options.window_sec,
        )

    def build_vocabulary(words: dict[str, list[str]], alpha: float) -> Any:
        """手がかりの強さを付けて Vocabulary を作る。"""
        return haas_asr.Vocabulary(words, alpha=alpha)

    return HaasEngine(
        model_name=args.model,
        dtype=args.dtype,
        device=args.device,
        transcribe=transcribe,
        transcribe_longform=transcribe_longform,
        build_vocabulary=build_vocabulary,
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
    """引数を読み、ログを設定し、モデルを読み込んでから 127.0.0.1 で待ち受ける。サーバーが止まると戻る。"""
    args = parse_args(argv)
    port = args.port
    _setup_logging()
    # 読み込みの間は待ち受けない（/health の応答が準備できたことを表す）
    try:
        engine = load_engine(args)
    except Exception:  # noqa: BLE001 標準エラーは常駐アプリが受けないため、種類を問わずログへ残す
        logger.exception("モデルの読み込みに失敗した")
        raise SystemExit(1) from None
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
