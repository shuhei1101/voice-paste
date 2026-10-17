@echo off
setlocal

rem Launcher log: overwritten on every launch (the app purges its own dated logs).
set "LOG_DIR=%LOCALAPPDATA%\voice-paste\log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "BAT_LOG=%LOG_DIR%\launcher.log"

echo [%date% %time%] voice-paste.bat start > "%BAT_LOG%"
echo [%date% %time%] cwd=%~dp0 >> "%BAT_LOG%"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\activate.bat" (
    echo [%date% %time%] activating .venv >> "%BAT_LOG%"
    call "%~dp0.venv\Scripts\activate.bat" >> "%BAT_LOG%" 2>&1
    if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\pythonw.exe"
) else (
    echo [%date% %time%] .venv not found, using system pythonw >> "%BAT_LOG%"
    set "PYTHON_EXE=pythonw"
)

echo [%date% %time%] launching: %PYTHON_EXE% -m voice_paste >> "%BAT_LOG%"
chcp 65001 > nul
set FOR_DISABLE_CONSOLE_CTRL_HANDLER=1
set "PATH=%~dp0.venv\Lib\site-packages\nvidia\cublas\bin;%~dp0.venv\Lib\site-packages\nvidia\cudnn\bin;%~dp0.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%PATH%"
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
