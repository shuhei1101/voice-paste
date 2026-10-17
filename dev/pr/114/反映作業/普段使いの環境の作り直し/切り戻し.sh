#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。実行で残した venv/ の Python で、前の起動のバッチファイルと同じ形で常駐アプリを起動し直す
set -uo pipefail

if [ ! -f venv/Scripts/pythonw.exe ]; then
  echo "残した venv: failed"
  exit 1
fi
echo "残した venv: ok"

if ! cmd.exe /c 'set "PATH=%CD%\venv\Lib\site-packages\nvidia\cublas\bin;%CD%\venv\Lib\site-packages\nvidia\cudnn\bin;%CD%\venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%PATH%" && start "" "%CD%\venv\Scripts\pythonw.exe" -m voice_paste'; then
  echo "venv での起動し直し: failed"
  exit 1
fi
echo "venv での起動し直し: changed"
