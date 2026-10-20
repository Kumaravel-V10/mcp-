@echo off
REM ─── Quick setup: install dependencies + create .env ───
REM Run this once on a fresh VM to set up everything.

cd /d "%~dp0"

echo [1/4] Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
pip install -r requirements.txt

echo [3/4] Creating .env from template...
if not exist .env (
    copy .env.example .env
    echo        Created .env — edit it with your settings.
) else (
    echo        .env already exists, skipping.
)

echo [4/4] Running readiness check...
python check.py

echo.
echo ─── Setup complete ───
echo.
echo Next steps:
echo   1. Edit .env (set MCP_HOST=0.0.0.0, set MCP_API_KEY, etc.)
echo   2. Open Windows Firewall port 3100
echo   3. Start the server:
echo        run-sse.bat                          (foreground)
echo        install-service.bat                  (Windows service)
echo.
pause
