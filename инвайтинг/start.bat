@echo off
setlocal

cd /d %~dp0

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

if "%INV_APP_HOST%"=="" set INV_APP_HOST=127.0.0.1
if "%INV_APP_PORT%"=="" set INV_APP_PORT=8011

python -m uvicorn app.main:app --host %INV_APP_HOST% --port %INV_APP_PORT%

endlocal
