@echo off
setlocal

set "LOG_DIR=%~dp0log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "TS=%%I"
set "BAT_LOG=%LOG_DIR%\%TS%_run_bat.log"

echo [%date% %time%] run.bat start >> "%BAT_LOG%"
echo [%date% %time%] cwd=%~dp0 >> "%BAT_LOG%"

if exist "%~dp0venv\Scripts\activate.bat" (
    echo [%date% %time%] activating venv >> "%BAT_LOG%"
    call "%~dp0venv\Scripts\activate.bat" >> "%BAT_LOG%" 2>&1
) else (
    echo [%date% %time%] venv not found, using system python >> "%BAT_LOG%"
)

echo [%date% %time%] launching: python -m voice_paste >> "%BAT_LOG%"
chcp 65001 > nul
python -m voice_paste >> "%BAT_LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo [%date% %time%] python exited with code %EXITCODE% >> "%BAT_LOG%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] python -m voice_paste exited with code %EXITCODE%
    echo See log: %BAT_LOG%
    pause
)

endlocal & exit /b %EXITCODE%
