@echo off
chcp 65001 >nul
cd /d "%~dp0Клонер чатов\ai_mirror"
title AI Mirror — мультичат

if not exist "multi_config.json" (
  echo Создайте multi_config.json из multi_config.example.json
  copy multi_config.example.json multi_config.json
  notepad multi_config.json
  pause
  exit /b 1
)

echo.
echo  AI Mirror — мультичат
echo  VPN должен быть включён
echo.
python -u run_multi.py
pause
