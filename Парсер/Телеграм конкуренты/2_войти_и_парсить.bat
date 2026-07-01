@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p CODE="Введите код из Telegram: "
python parser_telegram_web.py --phone "+79270467489" --code %CODE% --url "https://t.me/instachat6"
pause
