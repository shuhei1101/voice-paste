@echo off
chcp 65001 > nul

:: venv が存在する場合は自動有効化
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
)

python -m voice_paste
