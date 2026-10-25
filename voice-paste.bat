@echo off
setlocal

rem Launcher log: overwritten on every launch (the app purges its own dated logs).
set "LOG_DIR=%LOCALAPPDATA%\voice-paste\log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "BAT_LOG=%LOG_DIR%\launcher.log"

echo [%date% %time%] voice-paste.bat start > "%BAT_LOG%"
echo [%date% %time%] cwd=%~dp0 >> "%BAT_LOG%"

rem uv: PATH first, then the default install location.
set "UV_EXE="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV_EXE set "UV_EXE=%%i"
if not defined UV_EXE if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"

if defined UV_EXE goto sync
echo [%date% %time%] uv not found, skipping uv sync >> "%BAT_LOG%"
goto check

:sync
echo [%date% %time%] uv: %UV_EXE% >> "%BAT_LOG%"
echo Syncing .venv with uv sync --frozen. See log: %BAT_LOG%
echo [%date% %time%] running: uv sync --frozen >> "%BAT_LOG%"
pushd "%~dp0"
call "%UV_EXE%" sync --frozen >> "%BAT_LOG%" 2>&1
set "SYNC_CODE=%ERRORLEVEL%"
popd
echo [%date% %time%] uv sync --frozen exited with code %SYNC_CODE% >> "%BAT_LOG%"
if "%SYNC_CODE%"=="0" goto check
set "FAIL_CODE=%SYNC_CODE%"
set "FAIL_MSG=[ERROR] uv sync --frozen failed with code %SYNC_CODE%."
goto fail

:check
"%~dp0.venv\Scripts\python.exe" -c "import voice_paste" >> "%BAT_LOG%" 2>&1
set "IMPORT_CODE=%ERRORLEVEL%"
echo [%date% %time%] import voice_paste from .venv exited with code %IMPORT_CODE% >> "%BAT_LOG%"
if "%IMPORT_CODE%"=="0" goto launch
set "FAIL_CODE=1"
set "FAIL_MSG=[ERROR] voice_paste cannot be imported from .venv after uv sync."
if not defined UV_EXE set "FAIL_MSG=[ERROR] uv not found. Install uv and run voice-paste.bat again."
goto fail

:launch
echo [%date% %time%] activating .venv >> "%BAT_LOG%"
call "%~dp0.venv\Scripts\activate.bat" >> "%BAT_LOG%" 2>&1
set "PYTHON_EXE=%~dp0.venv\Scripts\pythonw.exe"

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

:fail
echo [%date% %time%] %FAIL_MSG% >> "%BAT_LOG%"
echo.
echo %FAIL_MSG%
echo See log: %BAT_LOG%
pause
endlocal & exit /b %FAIL_CODE%
