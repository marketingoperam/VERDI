@echo off
chcp 65001 >nul
cd /d "%~dp0Клонер чатов\ai_mirror"
title AI Mirror

if not exist "..\shadowchat\sessions\tech_919866196541.session" (
    echo Сначала авторизуйте техаккаунт в shadowchat
    pause
    exit /b 1
)

pip install -r requirements.txt -q
echo.
echo AI Mirror — простой клонер на техаккаунте
echo Настройка чатов: config.json
echo.
python -u run.py
pause
