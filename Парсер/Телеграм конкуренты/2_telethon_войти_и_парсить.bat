@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p CODE="Введите код из Telegram: "
python tg_login.py --code %CODE%
echo.
echo Запуск парсера instachat6...
python parser_telegram_project.py --url "https://t.me/instachat6"
pause
