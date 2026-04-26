"""WhisperModel を独立サブプロセスで実行するワーカー。

メインプロセスとは stdin / stdout の JSON Lines プロトコルで通信する。
faster-whisper / CTranslate2 が RTX 50系 (Blackwell) でクラッシュしても
親プロセスは生き残れるよう隔離する目的。
"""

import faulthandler
import json
import os
import sys
from pathlib import Path

# このプロセスのクラッシュも親に分かるようログ化
_LOG_DIR = Path(os.environ.get("VOICE_PASTE_LOG_DIR", "."))
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _crash_log = open(_LOG_DIR / "worker_crash.log", "a", encoding="utf-8")
    faulthandler.enable(file=_crash_log, all_threads=True)
except Exception:
    faulthandler.enable(all_threads=True)


def _log(msg: str) -> None:
    """stderr 経由で親プロセスにログを送る（親側でvoice_paste loggerに転送される）。"""
    print(msg, file=sys.stderr, flush=True)


def _send(obj: dict) -> None:
    """stdout に JSON Lines を1行書く。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_request() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    return json.loads(line)


def _build_vad_parameters(req: dict) -> dict | None:
    if not req.get("vad_filter"):
        return None
    return {
        "threshold": req.get("vad_threshold", 0.5),
        "min_speech_duration_ms": req.get("vad_min_speech_ms", 250),
        "min_silence_duration_ms": req.get("vad_min_silence_ms", 2000),
    }


def main() -> int:
    # 最初の1行で初期化設定を受け取る
    init = _read_request()
    if init is None or init.get("action") != "init":
        _send({"event": "error", "message": "missing init request"})
        return 1

    _log(
        "Initializing WhisperModel: model={}, device={}, compute_type={}".format(
            init["model"], init["device"], init["compute_type"]
        )
    )
    from faster_whisper import WhisperModel

    model = WhisperModel(
        init["model"],
        device=init["device"],
        compute_type=init["compute_type"],
        cpu_threads=init.get("cpu_threads", 0),
        num_workers=init.get("num_workers", 1),
    )
    _log("WhisperModel initialized successfully.")
    _send({"event": "ready"})

    while True:
        try:
            req = _read_request()
        except json.JSONDecodeError as exc:
            _send({"event": "error", "message": f"json decode error: {exc}"})
            continue

        if req is None:
            _log("stdin closed, exiting worker.")
            return 0

        action = req.get("action")
        if action == "shutdown":
            _log("shutdown requested.")
            return 0
        if action != "transcribe":
            _send({"event": "error", "message": f"unknown action: {action}"})
            continue

        audio_file = req["audio_file"]
        _log(f"Starting transcription: file={audio_file}")
        try:
            segments, info = model.transcribe(
                audio_file,
                language=req.get("language"),
                beam_size=req.get("beam_size", 5),
                best_of=req.get("best_of", 5),
                temperature=req.get("temperature", 0.0),
                vad_filter=req.get("vad_filter", False),
                vad_parameters=_build_vad_parameters(req),
                condition_on_previous_text=req.get("condition_on_previous_text", False),
                no_speech_threshold=req.get("no_speech_threshold", 0.6),
            )
            _send({
                "event": "info",
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
            })

            lines: list[str] = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    lines.append(text)
                _send({
                    "event": "segment",
                    "end": segment.end,
                    "duration": info.duration,
                })
            result = "\n".join(lines)
            _log(f"Transcription completed: {len(result)} chars, {len(lines)} segments")
            _send({"event": "result", "text": result, "segments": len(lines)})
        except Exception as exc:
            _log(f"Transcription error: {type(exc).__name__}: {exc}")
            _send({"event": "error", "message": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    sys.exit(main())
