"""PoC: Open JTalk で書き出した E2E の文を cpu・int8 の large-v3 で起こし、期待する言葉と読み上げの長さを確かめる。"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from faster_whisper import WhisperModel

from tests.support.continuous import SHORT_GAP_SEC, THREE_SENTENCES, sentences_of
from tests.support.inprocess import (
    LONG_READING,
    SPEECH_TEXT,
    SPEECH_WORD,
    long_reading_texts,
    speech_sequence_input,
    synthesize_speech,
)
from voice_paste.features.recording.segmenter import MAX_SEGMENT_SEC

PAIRS = [(SPEECH_TEXT, SPEECH_WORD), *THREE_SENTENCES, *LONG_READING]

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    results = []
    for index, (text, word) in enumerate(dict.fromkeys(PAIRS)):
        wav = synthesize_speech(text, tmp_path / f"s{index}.wav")
        begin = time.monotonic()
        segments, _info = model.transcribe(str(wav), language="ja")
        got = "".join(segment.text for segment in segments)
        results.append({"text": text, "word": word, "got": got, "ok": word in got, "sec": round(time.monotonic() - begin, 2)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    long_input = speech_sequence_input(tmp_path, sentences_of(LONG_READING), gap_sec=SHORT_GAP_SEC)
    # tests/nfr/test_max_segment_length.py と同じ間（0.4 秒）と前の無音（1 秒）でつなぐ
    reading = speech_sequence_input(tmp_path, long_reading_texts(), gap_sec=0.4, lead_silence_sec=1.0)
    print(json.dumps({
        "ok_count": sum(r["ok"] for r in results), "total": len(results),
        "long_reading_sequence_sec": round(long_input.duration_sec, 2),
        "long_reading_texts_sec": round(reading.duration_sec, 2),
        "MAX_SEGMENT_SEC": MAX_SEGMENT_SEC,
    }, ensure_ascii=False))
