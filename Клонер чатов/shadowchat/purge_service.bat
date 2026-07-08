@echo off
chcp 65001 >nul
title Очистка сервисных сообщений
cd /d "%~dp0"
echo.
echo  Очистка «вступил / пригласил / вышел» — работает параллельно с клонером
echo.
python scripts/purge_service_messages.py %*
if errorlevel 1 pause
