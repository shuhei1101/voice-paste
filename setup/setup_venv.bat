@echo off
cd /d "%~dp0.."

echo [voice-paste] Setting up virtual environment...

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11 or later.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist "venv" (
    if not exist "venv\Scripts\activate.bat" (
        echo [WARN] Broken venv detected ^(no Scripts\activate.bat^). Removing...
        rmdir /s /q "venv"
    )
)

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
) else (
    echo [INFO] Virtual environment already exists. Skipping creation.
)

call venv\Scripts\activate.bat

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

echo [INFO] Installing dependencies...
pip install -e .

echo [INFO] Checking CUDA availability...
python -c "import torch; print('[INFO] CUDA available:', torch.cuda.is_available())" 2>nul || (
    echo [INFO] torch not installed. Checking ctranslate2 CUDA support...
    python -c "import ctranslate2; print('[INFO] ctranslate2 CUDA support:', ctranslate2.get_cuda_device_count() ^> 0)" 2>nul || echo [INFO] CUDA check skipped.
)

echo.
echo [voice-paste] Setup completed successfully!
echo Run: run.bat
pause
