@echo off
REM ─── SC-MCP-SERVER: Start in SSE (HTTP) mode on Windows VM ───
REM Exposes the MCP server over HTTP so external clients can connect.
REM
REM Usage:
REM   run-sse.bat                    (defaults: 0.0.0.0:3100)
REM   run-sse.bat --port 8080        (custom port)
REM   run-sse.bat --host 10.0.0.5    (bind to specific IP)

cd /d "%~dp0"

REM Load .env file if it exists
if exist .env (
    for /f "usebackaliases tokens=1,* delims==" %%a in ('type .env ^| findstr /v "^#" ^| findstr /v "^$"') do (
        set "%%a=%%b"
    )
)

REM Activate venv if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

echo [SC-MCP-SERVER] Starting in SSE mode...
echo [SC-MCP-SERVER] Endpoint: http://%MCP_HOST%:%MCP_PORT%/sse
echo [SC-MCP-SERVER] Health:   http://%MCP_HOST%:%MCP_PORT%/health
echo [SC-MCP-SERVER] Tools:    http://%MCP_HOST%:%MCP_PORT%/api/tools
echo.

python server.py --transport sse %*
