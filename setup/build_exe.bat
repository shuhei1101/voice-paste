@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%"

set "LOG_DIR=%PROJECT_ROOT%\log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "TS=%%I"
set "BAT_LOG=%LOG_DIR%\%TS%_build_exe_bat.log"

echo [%date% %time%] build_exe.bat start >> "%BAT_LOG%"
echo [%date% %time%] cwd=%CD% >> "%BAT_LOG%"

if exist "%PROJECT_ROOT%\venv\Scripts\activate.bat" (
    echo [%date% %time%] activating venv >> "%BAT_LOG%"
    call "%PROJECT_ROOT%\venv\Scripts\activate.bat" >> "%BAT_LOG%" 2>&1
) else (
    echo [%date% %time%] venv not found, aborting >> "%BAT_LOG%"
    echo [ERROR] venv not found. Run setup\setup_venv.bat first.
    popd
    endlocal & exit /b 1
)

chcp 65001 > nul

echo [%date% %time%] checking pyinstaller >> "%BAT_LOG%"
python -m pip show pyinstaller >> "%BAT_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] installing pyinstaller >> "%BAT_LOG%"
    python -m pip install pyinstaller >> "%BAT_LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] failed to install pyinstaller
        echo See log: %BAT_LOG%
        popd
        endlocal & exit /b 1
    )
)

echo [%date% %time%] stopping running voice-paste.exe >> "%BAT_LOG%"
taskkill /f /im voice-paste.exe >nul 2>&1
echo [%date% %time%] waiting for process cleanup >> "%BAT_LOG%"
timeout /t 2 /nobreak >nul

echo [%date% %time%] removing previous dist >> "%BAT_LOG%"
if exist "%PROJECT_ROOT%\dist\voice-paste" rmdir /s /q "%PROJECT_ROOT%\dist\voice-paste" >> "%BAT_LOG%" 2>&1
if exist "%PROJECT_ROOT%\dist\voice-paste" (
    echo [ERROR] cannot remove dist\voice-paste. Running voice-paste.exe may be locking it.
    echo See log: %BAT_LOG%
    popd
    endlocal & exit /b 1
)

echo [%date% %time%] removing build cache >> "%BAT_LOG%"
if exist "%PROJECT_ROOT%\build" rmdir /s /q "%PROJECT_ROOT%\build" >> "%BAT_LOG%" 2>&1

echo [%date% %time%] running pyinstaller >> "%BAT_LOG%"

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name voice-paste ^
    --icon "%PROJECT_ROOT%\resources\icon.ico" ^
    --distpath "%PROJECT_ROOT%\dist" ^
    --workpath "%PROJECT_ROOT%\build" ^
    --specpath "%PROJECT_ROOT%\build" ^
    --add-data "%PROJECT_ROOT%\resources;resources" ^
    --add-data "%PROJECT_ROOT%\.env.sample;." ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all pystray ^
    --collect-all PIL ^
    --collect-all nvidia.cublas ^
    --collect-all nvidia.cudnn ^
    --collect-all nvidia.cuda_nvrtc ^
    --collect-all openai ^
    --collect-all httpx ^
    --hidden-import sounddevice ^
    --hidden-import scipy ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    "%PROJECT_ROOT%\voice_paste\__main__.py" 2>&1 | powershell -NoProfile -Command "[Console]::InputEncoding=[System.Text.Encoding]::UTF8; $input | ForEach-Object { Write-Host $_; Add-Content -LiteralPath '%BAT_LOG%' -Value $_ -Encoding utf8 }"

if not exist "%PROJECT_ROOT%\dist\voice-paste\voice-paste.exe" (
    echo [%date% %time%] pyinstaller failed ^(exe not produced^) >> "%BAT_LOG%"
    echo.
    echo [ERROR] pyinstaller failed. exe not produced.
    echo See log: %BAT_LOG%
    popd
    endlocal & exit /b 1
)
echo [%date% %time%] pyinstaller completed >> "%BAT_LOG%"

echo [%date% %time%] copying manual.txt and yogo.csv to dist root >> "%BAT_LOG%"
if exist "%PROJECT_ROOT%\dist\voice-paste\_internal\resources\manual.txt" (
    copy /y "%PROJECT_ROOT%\dist\voice-paste\_internal\resources\manual.txt" "%PROJECT_ROOT%\dist\voice-paste\manual.txt" >> "%BAT_LOG%" 2>&1
)
if exist "%PROJECT_ROOT%\dist\voice-paste\_internal\resources\yogo.csv" (
    copy /y "%PROJECT_ROOT%\dist\voice-paste\_internal\resources\yogo.csv" "%PROJECT_ROOT%\dist\voice-paste\yogo.csv" >> "%BAT_LOG%" 2>&1
)

echo [%date% %time%] build complete: dist\voice-paste\voice-paste.exe >> "%BAT_LOG%"
echo.
echo [OK] build complete: dist\voice-paste\voice-paste.exe
echo See log: %BAT_LOG%

popd
endlocal & exit /b 0
