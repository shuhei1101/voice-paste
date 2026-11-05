#!/usr/bin/env bash
# PoC の検証のサーバーを WSL の中で起動する。Windows からは wsl.exe -e bash start_server.sh で呼ぶ
set -euo pipefail
cd "$(dirname "$0")"
exec "${HAAS_VENV:-$HOME/haas-poc/Haas-ASR/.venv}/bin/uvicorn" --app-dir . server:app --host 127.0.0.1 --port "${HAAS_PORT:-18990}" --log-level warning
