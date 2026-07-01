@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
echo === Запрос кода Telegram ===
echo Код обычно приходит В ПРИЛОЖЕНИЕ, не SMS!
echo.
python scripts\telegram_request_code.py
pause
