@echo off
chcp 65001 >nul
cd /d "%~dp0Клонер чатов\ai_mirror"
title Клон форума multi12000
echo.
echo  Создание нового мультичата-копии @multi12000
echo  VPN должен быть включён
echo.
python -u clone_forum.py %*
pause
