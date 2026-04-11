@echo off
chcp 65001 > nul
cd /d "%~dp0.."

echo [voice-paste] Setting up virtual environment...

:: Python の存在確認
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11 or later.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

:: venv 作成
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
) else (
    echo [INFO] Virtual environment already exists. Skipping creation.
)

:: venv 有効化
call venv\Scripts\activate.bat

:: pip アップグレード
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

:: 依存ライブラリのインストール
echo [INFO] Installing dependencies...
pip install -e .

:: GPU（CUDA）対応の確認
echo [INFO] Checking CUDA availability...
python -c "import torch; print('[INFO] CUDA available:', torch.cuda.is_available())" 2>nul || (
    echo [INFO] torch not installed. Checking ctranslate2 CUDA support...
    python -c "import ctranslate2; print('[INFO] ctranslate2 CUDA support:', ctranslate2.get_cuda_device_count() > 0)" 2>nul || echo [INFO] CUDA check skipped.
)

echo.
echo [voice-paste] Setup completed successfully!
echo Run: run.bat
pause
