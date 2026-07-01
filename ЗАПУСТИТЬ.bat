@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Verdi Monitor: запуск ===

if not exist "data" mkdir data
if not exist "backend\sessions" mkdir backend\sessions

set PYTHONPATH=%CD%\backend;%CD%
set PATH=%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts;%PATH%

cd backend
pip install -r requirements.txt -q

start "Verdi Backend" cmd /k "cd /d %CD% && set PYTHONPATH=%CD%\..\\backend;%CD%\.. && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

cd ..\frontend
if not exist "node_modules" call npm install
start "Verdi Frontend" cmd /k "cd /d %CD% && npm run dev"

echo.
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
echo.
echo Панель в Cursor: Ctrl+Shift+P -^> Simple Browser: Show -^> http://127.0.0.1:5173
echo Или: Terminal -^> Run Task -^> Verdi: открыть панель в браузере Cursor
echo.
pause
