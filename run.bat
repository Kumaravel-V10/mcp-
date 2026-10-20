@echo off
REM ─── SC-MCP-SERVER: Start in stdio mode (local AI client) ───
cd /d "%~dp0"

if exist .env (
    for /f "usebackaliases tokens=1,* delims==" %%a in ('type .env ^| findstr /v "^#" ^| findstr /v "^$"') do (
        set "%%a=%%b"
    )
)

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python server.py --transport stdio
