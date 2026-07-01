@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запрос кода Telethon...
python tg_login.py
pause
