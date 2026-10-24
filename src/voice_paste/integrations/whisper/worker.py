"""文字起こしワーカーの子プロセスの入口。faster-whisper のモデルを持ち、標準入出力の JSON Lines で受けた録音を起こす。"""

from __future__ import annotations

import faulthandler
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from voice_paste.integrations.whisper.protocol import WorkerMessage

logger = logging.getLogger(__name__)

CRASH_LOG_NAME: str = "worker_crash.log"
"""ワーカーが落ちたときのスタックを書くファイルの名前（config で受けたログの置き場所の下）。"""

STDIO_ENCODING: str = "utf-8"
"""標準入出力の文字コード。"""

EXIT_OK: int = 0
"""標準入力が閉じて終わった。"""

EXIT_STARTUP_FAILED: int = 1
"""config を受けられない・モデルを読めずに終わった。"""


def load_faster_whisper_model(config: dict[str, Any]) -> Any:  # noqa: ANN401 faster-whisper を遅延 import するため型を持てない
    """config のモデル・デバイス・量子化で faster-whisper のモデルを読む。"""
    from faster_whisper import WhisperModel

    return WhisperModel(
        config["model"],
        device=config["device"],
        compute_type=config["compute_type"],
        cpu_threads=config["cpu_threads"],
        num_workers=config["num_workers"],
    )


def _send(stdout: TextIO, message_type: str, **payload: Any) -> None:  # noqa: ANN401 種類ごとに中身が違う
    """標準出力へメッセージを 1 行書く。"""
    stdout.write(WorkerMessage(type=message_type, payload=payload).to_line())
    stdout.flush()


def _build_vad_parameters(request: dict[str, Any]) -> dict[str, Any] | None:
    """VAD がオンなら faster-whisper に渡す VAD の引数を作る。オフなら None を返す。"""
    if not request["vad_filter"]:
        return None
    return {
        "threshold": request["vad_threshold"],
        "min_speech_duration_ms": request["vad_min_speech_ms"],
        "min_silence_duration_ms": request["vad_min_silence_ms"],
    }


def _transcribe(model: Any, request: dict[str, Any], stdout: TextIO) -> None:  # noqa: ANN401 faster-whisper のモデル
    """1 件の録音を起こし、区間ごとに progress、最後に result を書く。"""
    segments, info = model.transcribe(
        request["audio_path"],
        language=request["language"],
        beam_size=request["beam_size"],
        best_of=request["best_of"],
        temperature=request["temperature"],
        vad_filter=request["vad_filter"],
        vad_parameters=_build_vad_parameters(request),
        condition_on_previous_text=request["condition_on_previous_text"],
        no_speech_threshold=request["no_speech_threshold"],
        word_timestamps=request.get("word_timestamps", False),
        hallucination_silence_threshold=request.get("hallucination_silence_threshold"),
        # 手がかり（無ければ None）。prefix は渡さない（渡すと hotwords が効かない）
        hotwords=request.get("hotwords"),
    )

    texts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        # 空の区間は result に含めない（progress は区間ごとに返す）
        if text:
            texts.append(text)
        _send(stdout, "progress", end=segment.end, duration=info.duration)
    _send(stdout, "result", segments=texts)
    logger.info(f"文字に起こした（区間 {len(texts)}・{sum(len(text) for text in texts)} 文字）")


def _read_config(stdin: TextIO) -> dict[str, Any]:
    """最初の 1 行を config として読む。config でなければ ValueError を送出する。"""
    message = WorkerMessage.from_line(stdin.readline())
    if message.type != "config":
        raise ValueError(f"最初の行が config でない（{message.type}）")
    return message.payload


def _serve(
    stdin: TextIO, stdout: TextIO, model: Any  # noqa: ANN401 faster-whisper のモデル
) -> None:
    """transcribe を 1 件ずつ処理する。標準入力が閉じたら戻る。"""
    for line in iter(stdin.readline, ""):
        if not line.strip():
            continue
        # 1 件の失敗では終わらず、error を返して次の行を待つ（CUDA のクラッシュはプロセスごと落ちる）
        try:
            message = WorkerMessage.from_line(line)
            if message.type != "transcribe":
                raise ValueError(f"知らない種類（{message.type}）")
            _transcribe(model, message.payload, stdout)
        except (ValidationError, ValueError) as error:
            logger.warning(f"読めない行を断った（{error}）")
            _send(stdout, "error", message=f"{type(error).__name__}: {error}")
        except Exception as error:  # noqa: BLE001 最上位で受け、常駐側へ error として返す
            logger.exception("文字起こしに失敗した")
            _send(stdout, "error", message=f"{type(error).__name__}: {error}")


def run_worker(
    stdin: TextIO,
    stdout: TextIO,
    load_model: Callable[[dict[str, Any]], Any],
) -> int:
    """config を受けてモデルを読み、ready を返してから transcribe を 1 件ずつ処理する。終了コードを返す。"""
    # 1. config を読み、クラッシュの記録を向けてからモデルを読む
    try:
        config = _read_config(stdin)
        log_dir = Path(config["log_dir"])
        log_dir.mkdir(parents=True, exist_ok=True)
        crash_log = (log_dir / CRASH_LOG_NAME).open("a", encoding=STDIO_ENCODING)
    except (ValidationError, ValueError, KeyError, OSError) as error:
        _send(stdout, "error", message=f"{type(error).__name__}: {error}")
        return EXIT_STARTUP_FAILED

    with crash_log:
        faulthandler.enable(file=crash_log, all_threads=True)
        try:
            try:
                model = load_model(config)
            except Exception as error:  # noqa: BLE001 モデルを読めない理由は何でも error として返す
                logger.exception("モデルを読めなかった")
                _send(stdout, "error", message=f"{type(error).__name__}: {error}")
                return EXIT_STARTUP_FAILED

            # 2. ready を書き、3. transcribe を処理し、4. 標準入力が閉じたら終わる
            _send(stdout, "ready")
            _serve(stdin, stdout, model)
            return EXIT_OK
        finally:
            faulthandler.disable()


def main() -> int:
    """標準入出力を UTF-8 にし、ログを標準エラーへ向けてワーカーを動かす。"""
    sys.stdin.reconfigure(encoding=STDIO_ENCODING)  # type: ignore[attr-defined]
    sys.stdout.reconfigure(encoding=STDIO_ENCODING)  # type: ignore[attr-defined]
    # 標準出力にはメッセージだけを書くため、ログは標準エラーへ書く
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    return run_worker(sys.stdin, sys.stdout, load_faster_whisper_model)


if __name__ == "__main__":
    sys.exit(main())
