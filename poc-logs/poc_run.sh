#!/bin/bash
cd ~/vp-251
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority
mkdir -p poc-logs
date -Is > poc-logs/started
.venv/bin/python -m pytest tests/e2e --run-e2e -v -rs -p no:cacheprovider > poc-logs/e2e.log 2>&1
echo "exit=$?" >> poc-logs/e2e.log
.venv/bin/python -m pytest tests/nfr --run-e2e -v -s -rs -p no:cacheprovider > poc-logs/nfr.log 2>&1
echo "exit=$?" >> poc-logs/nfr.log
cat > tests/nfr/fixtures/whisper.env <<'ENV'
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_CPU_THREADS=0
WHISPER_NUM_WORKERS=1
WHISPER_BEAM_SIZE=10
WHISPER_BEST_OF=5
WHISPER_LANGUAGE=ja
WHISPER_VAD_FILTER=true
WHISPER_VAD_THRESHOLD=0.5
WHISPER_VAD_MIN_SPEECH_MS=250
WHISPER_VAD_MIN_SILENCE_MS=2000
WHISPER_CONDITION_ON_PREVIOUS_TEXT=false
WHISPER_TEMPERATURE=0.0
WHISPER_NO_SPEECH_THRESHOLD=0.6
ENV
VOICE_PASTE_POC_ALLOW_CPU=1 .venv/bin/python -m pytest tests/nfr/test_worker_recovery_time.py tests/nfr/test_worker_stop_timeout.py tests/nfr/test_single_instance_timeout.py tests/nfr/test_transcription_parity.py tests/nfr/test_paste_latency.py --run-e2e -v -s -rs -p no:cacheprovider > poc-logs/nfr_cpu.log 2>&1
echo "exit=$?" >> poc-logs/nfr_cpu.log
rm -f tests/nfr/fixtures/whisper.env
date -Is > poc-logs/done
