"""PoC: 形式ごとの音声を作り、decode_audio の長さと、今のワーカーで起こした文字の CER を確かめる。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import av
from faster_whisper import decode_audio

from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.shared.settings import LocalWhisperSettings

OUT_DIR: Path = Path(__file__).parent / "out"
"""音声と結果の置き場所。"""

SOURCE_WAV: Path = OUT_DIR / "speech.wav"
"""元の読み上げの WAV。"""

SAMPLE_RATE: int = 16000
"""decode_audio が返す配列のサンプリングレート。"""

BIT_RATE: int = 32000
"""PyAV で作る形式のビットレート（MediaRecorder の audioBitsPerSecond に揃える）。"""

LENGTH_TOLERANCE_SEC: float = 0.1
"""元の WAV との長さの差の許容。"""

CER_LIMIT: float = 0.05
"""元の WAV で起こした文字との文字誤り率の上限。"""

READY_TIMEOUT_SEC: float = 600.0
"""ワーカーの ready を待つ上限（モデルの読み込みを含む）。"""

STOP_TIMEOUT_SEC: float = 5.0
"""ワーカーの終わりを待つ時間。"""

# 形式の名前 → (ファイル名, コンテナ, コーデック, コンテナのオプション)
ENCODED_FORMATS: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "ogg/opus（PyAV）": ("pyav.ogg", "ogg", "libopus", {}),
    "MP3（PyAV）": ("pyav.mp3", "mp3", "libmp3lame", {}),
    "fragmented MP4 AAC（PyAV）": (
        "pyav_frag.mp4",
        "mp4",
        "aac",
        {"movflags": "frag_keyframe+empty_moov+default_base_moof"},
    ),
}

RECORDED_FORMATS: dict[str, str] = {
    "webm/opus（Edge の MediaRecorder）": "edge_audio_webm_codecs_opus",
    "mp4 AAC（Edge の MediaRecorder）": "edge_audio_mp4_codecs_mp4a_40_2",
}


def _encode(source: Path, target: Path, container: str, codec: str, options: dict[str, str]) -> None:
    """元の WAV を指定のコンテナとコーデックへ書き直す。"""
    with av.open(str(source)) as src, av.open(str(target), "w", format=container, options=options) as dst:
        stream = dst.add_stream(codec, rate=48000 if codec == "libopus" else 44100)
        stream.bit_rate = BIT_RATE
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=stream.rate)
        for frame in src.decode(audio=0):
            for resampled in resampler.resample(frame):
                for packet in stream.encode(resampled):
                    dst.mux(packet)
        for resampled in resampler.resample(None):
            for packet in stream.encode(resampled):
                dst.mux(packet)
        for packet in stream.encode(None):
            dst.mux(packet)


def _describe(path: Path) -> dict[str, object]:
    """コンテナ・コーデック・ビットレート・コンテナが持つ長さを返す（構造の違いの記録用）。"""
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        return {
            "format": container.format.name,
            "codec": stream.codec_context.name,
            "container_duration_sec": None if container.duration is None else container.duration / 1e6,
            "bit_rate": container.bit_rate,
            "size": path.stat().st_size,
        }


def _cer(reference: str, hypothesis: str) -> float:
    """空白と改行を除いた文字の編集距離を参照の長さで割る。"""
    ref = "".join(reference.split())
    hyp = "".join(hypothesis.split())
    previous = list(range(len(hyp) + 1))
    for i, ref_char in enumerate(ref, 1):
        current = [i]
        for j, hyp_char in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char)))
        previous = current
    return previous[-1] / max(len(ref), 1)


def main() -> int:
    """形式を作り、長さと CER を突き合わせて結果を JSON で書く。"""
    # 1. PyAV で ogg/opus・MP3・fragmented MP4 の AAC を作る
    targets: dict[str, Path] = {}
    for label, (name, container, codec, options) in ENCODED_FORMATS.items():
        path = OUT_DIR / name
        _encode(SOURCE_WAV, path, container, codec, options)
        targets[label] = path
    for label, name in RECORDED_FORMATS.items():
        targets[label] = OUT_DIR / name

    # 2. 元の WAV と各形式を decode_audio で 16kHz の配列にし、長さを比べる
    source_len = len(decode_audio(str(SOURCE_WAV), sampling_rate=SAMPLE_RATE)) / SAMPLE_RATE
    rows: dict[str, dict[str, object]] = {}
    for label, path in targets.items():
        row: dict[str, object] = {"file": path.name, **_describe(path)}
        try:
            samples = decode_audio(str(path), sampling_rate=SAMPLE_RATE)
            row["decoded_sec"] = round(len(samples) / SAMPLE_RATE, 3)
            row["decode_error"] = None
        except Exception as error:  # noqa: BLE001 PoC の記録として全ての失敗を残す
            row["decoded_sec"] = None
            row["decode_error"] = repr(error)
        rows[label] = row

    # 3. 今のワーカーで元の WAV と各形式を起こし、CER を求める
    client = WhisperWorkerClient(
        settings=LocalWhisperSettings(),
        ready_timeout_sec=READY_TIMEOUT_SEC,
        log_dir=OUT_DIR,
        stop_timeout_sec=STOP_TIMEOUT_SEC,
    )
    client.start(ready_timeout_sec=READY_TIMEOUT_SEC)
    try:
        reference = "\n".join(client.transcribe(SOURCE_WAV))
        for label, path in targets.items():
            text = "\n".join(client.transcribe(path))
            rows[label]["text"] = text
            rows[label]["cer"] = round(_cer(reference, text), 4)
    finally:
        client.stop()

    # 4. 成功条件と突き合わせる（Edge の録音は MediaRecorder が録った時間、PyAV の形式は元の WAV の長さと比べる）
    for label, row in rows.items():
        decoded = row["decoded_sec"]
        if label in RECORDED_FORMATS:
            meta = json.loads((OUT_DIR / f"{RECORDED_FORMATS[label]}.json").read_text(encoding="utf-8"))
            expected_sec = meta["elapsed_ms"] / 1000
        else:
            expected_sec = source_len
        row["expected_sec"] = round(expected_sec, 3)
        row["length_ok"] = decoded is not None and abs(float(decoded) - expected_sec) <= LENGTH_TOLERANCE_SEC
        row["cer_ok"] = float(row["cer"]) <= CER_LIMIT
    result = {"source_sec": round(source_len, 3), "reference_text": reference, "formats": rows}
    (OUT_DIR / "formats.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
