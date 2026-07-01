@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запрос кода на +13309563469 ...
python parser_telegram_web.py --phone "+79270467489" --request-code
pause
