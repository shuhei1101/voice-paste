@echo off
setlocal

set "LOG_DIR=%~dp0log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "TS=%%I"
set "BAT_LOG=%LOG_DIR%\%TS%_run_tray_bat.log"

echo [%date% %time%] run_tray.bat start >> "%BAT_LOG%"
echo [%date% %time%] cwd=%~dp0 >> "%BAT_LOG%"

set "PYTHON_EXE=python"
if exist "%~dp0venv\Scripts\activate.bat" (
    echo [%date% %time%] activating venv >> "%BAT_LOG%"
    call "%~dp0venv\Scripts\activate.bat" >> "%BAT_LOG%" 2>&1
    if exist "%~dp0venv\Scripts\pythonw.exe" set "PYTHON_EXE=%~dp0venv\Scripts\pythonw.exe"
) else (
    echo [%date% %time%] venv not found, using system pythonw >> "%BAT_LOG%"
    set "PYTHON_EXE=pythonw"
)

echo [%date% %time%] launching: %PYTHON_EXE% -m voice_paste >> "%BAT_LOG%"
chcp 65001 > nul
start "" "%PYTHON_EXE%" -m voice_paste
set "EXITCODE=%ERRORLEVEL%"
echo [%date% %time%] launcher exited with code %EXITCODE% >> "%BAT_LOG%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] failed to launch voice_paste with code %EXITCODE%
    echo See log: %BAT_LOG%
    pause
)

endlocal & exit /b %EXITCODE%
