@echo off
chcp 65001 >nul
cd /d "%~dp0Клонер чатов\shadowchat"
title ShadowChat
if not exist ".env" copy .env.example .env >nul
pip install -r requirements.txt -q
echo.
echo ShadowChat: http://127.0.0.1:8001
echo Для Cursor: Ctrl+Shift+P -^> Simple Browser: Show -^> http://127.0.0.1:8001
echo.
python run.py
