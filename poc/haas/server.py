"""PoC の検証のサーバー。WSL の中で Haas-ja-v1.0 を読み込み、POST された WAV を起こして返却する。

起動: `.venv/bin/uvicorn --app-dir {このフォルダ} server:app --host 127.0.0.1 --port 18990`
"""

import io
import time
from typing import Literal

import haas_asr
import torch
from fastapi import FastAPI, Form, UploadFile
from haas_asr.longform import split_at_quiet_points

from sentences import HINT_WORDS

MODEL_NAME = "third-intelligence/Haas-ja-v1.0"
# モデルが学習した発話の長さの上限。これを超える音声は transcribe_longform で区切って起こす
SHORT_LIMIT_SEC = 30.0
LONGFORM_BATCH_SIZE = 64

started_at = time.perf_counter()
model = haas_asr.load_model(MODEL_NAME)
loaded_sec = time.perf_counter() - started_at

# V1: 表記ごとに読みを指定する。V2: 読みを指定せず表記だけを指定する（読みを入力させない構成）
VOCABULARIES: dict[str, haas_asr.Vocabulary | None] = {
    "none": None,
    "v1": haas_asr.Vocabulary({written: [reading] for written, reading in HINT_WORDS}),
    "v2": haas_asr.Vocabulary([written for written, _ in HINT_WORDS]),
}

app = FastAPI()


def _gpu_memory_mb() -> dict[str, float]:
    """このプロセスが確保している GPU のメモリ（MiB）を返す。"""
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 2**20, 1),
        "reserved_mb": round(torch.cuda.memory_reserved() / 2**20, 1),
        "max_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1),
    }


@app.get("/health")
def health() -> dict[str, object]:
    """モデルを読み込み終えたことと、読み込みにかかった秒数を返す。"""
    return {"ok": True, "model_load_sec": round(loaded_sec, 2), "device": torch.cuda.get_device_name(), **_gpu_memory_mb()}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile,
    vocab: Literal["none", "v1", "v2"] = Form("none"),
    longform_mode: Literal["batch", "sequential"] = Form("batch"),
) -> dict[str, object]:
    """1 件の音声を起こし、起こした文字・かかった秒数・区切った数を返す。"""
    data = await audio.read()
    samples = haas_asr.load_audio(io.BytesIO(data))
    duration = len(samples) / 16000
    vocabulary = VOCABULARIES[vocab]
    torch.cuda.synchronize()
    begin = time.perf_counter()
    chunk_count = 1
    # 30 秒以下か
    if duration <= SHORT_LIMIT_SEC:
        # 短い: 1 件のまま transcribe で起こす
        text = haas_asr.transcribe(model, [samples], vocabulary=vocabulary)[0]
    elif longform_mode == "batch":
        # 長い・まとめて: transcribe_longform が静かな箇所で区切り、まとめて起こす（途中の進みは返せない）
        chunk_count = len(split_at_quiet_points(samples))
        text = haas_asr.transcribe_longform(model, samples, batch_size=LONGFORM_BATCH_SIZE, vocabulary=vocabulary)
    else:
        # 長い・1 つずつ: 同じ区切りを 1 つずつ起こす（区切りごとに進みを返せる構成の時間を測る）
        spans = split_at_quiet_points(samples)
        chunk_count = len(spans)
        texts = [haas_asr.transcribe(model, [samples[s:e]], vocabulary=vocabulary)[0] for s, e in spans]
        text = "".join(texts)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - begin
    return {
        "text": text,
        "duration_sec": round(duration, 2),
        "transcribe_sec": round(elapsed, 3),
        "chunk_count": chunk_count,
        **_gpu_memory_mb(),
    }
