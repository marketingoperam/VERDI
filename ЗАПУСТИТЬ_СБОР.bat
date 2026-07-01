@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
echo === Запуск сбора Telegram ===
python scripts\run_telegram_collect.py
pause
