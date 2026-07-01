@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
echo === Запрос кода по SMS ===
python scripts\telegram_request_code.py --sms
pause
