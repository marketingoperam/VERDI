@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
echo === Вход в Telegram (введите код) ===
python scripts\telegram_login.py
pause
