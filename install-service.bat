@echo off
REM ─── Install SC-MCP-SERVER as a Windows Service using NSSM ───
REM
REM Prerequisites:
REM   1. Download NSSM from https://nssm.cc/download
REM   2. Extract nssm.exe to a folder in PATH (e.g. C:\tools\nssm.exe)
REM   3. Run this script as Administrator
REM
REM This creates a Windows service that auto-starts on boot and
REM restarts on failure.

setlocal
cd /d "%~dp0"

set SERVICE_NAME=SC-MCP-SERVER
set PYTHON_EXE=python
set SERVER_SCRIPT=%~dp0server.py
set LOG_DIR=%~dp0logs

REM Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Run this script as Administrator.
    pause
    exit /b 1
)

REM Check NSSM is available
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] nssm.exe not found in PATH.
    echo         Download from https://nssm.cc/download
    pause
    exit /b 1
)

REM Resolve Python path
for /f "delims=" %%i in ('where python') do set PYTHON_EXE=%%i
if exist "%~dp0venv\Scripts\python.exe" (
    set PYTHON_EXE=%~dp0venv\Scripts\python.exe
)

REM Create logs directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo ─── Installing %SERVICE_NAME% ───
echo Python:  %PYTHON_EXE%
echo Script:  %SERVER_SCRIPT%
echo Logs:    %LOG_DIR%
echo.

REM Install the service
nssm install %SERVICE_NAME% "%PYTHON_EXE%" "%SERVER_SCRIPT% --transport sse --host 0.0.0.0 --port 3100"

REM Configure working directory
nssm set %SERVICE_NAME% AppDirectory "%~dp0"

REM Configure logging
nssm set %SERVICE_NAME% AppStdout "%LOG_DIR%\stdout.log"
nssm set %SERVICE_NAME% AppStderr "%LOG_DIR%\stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 10485760

REM Configure restart on failure
nssm set %SERVICE_NAME% AppRestartDelay 5000

REM Configure description
nssm set %SERVICE_NAME% Description "NevioServiceCenter MCP Server - AI booking agent tools"
nssm set %SERVICE_NAME% DisplayName "SC-MCP-SERVER"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START

REM Load .env variables into service environment
if exist "%~dp0.env" (
    echo Loading environment from .env...
    set ENV_VARS=
    for /f "usebackq tokens=1,* delims==" %%a in (`type "%~dp0.env" ^| findstr /v "^#" ^| findstr /v "^$"`) do (
        nssm set %SERVICE_NAME% AppEnvironmentExtra +%%a=%%b
    )
)

echo.
echo [OK] Service installed: %SERVICE_NAME%
echo.
echo Commands:
echo   nssm start %SERVICE_NAME%       Start the service
echo   nssm stop %SERVICE_NAME%        Stop the service
echo   nssm restart %SERVICE_NAME%     Restart the service
echo   nssm status %SERVICE_NAME%      Check status
echo   nssm remove %SERVICE_NAME%      Uninstall the service
echo   nssm edit %SERVICE_NAME%        Edit service config (GUI)
echo.
echo After starting, the server will be available at:
echo   http://^<VM-IP^>:3100/sse         MCP SSE endpoint
echo   http://^<VM-IP^>:3100/health      Health check
echo   http://^<VM-IP^>:3100/api/tools   HTTP API
echo.
pause
