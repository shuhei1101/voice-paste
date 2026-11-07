#!/usr/bin/env bash
# wsl.exe の -e bash は .profile を読まず uv が見つからないため、環境の python を絶対パスで起動する。
cd "$(dirname "$0")/.." || exit 1
exec "$HOME/.local/share/voice-paste/haas_server/.venv/bin/python" -m haas_server.main "$@"
