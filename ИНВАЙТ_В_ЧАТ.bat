@echo off
chcp 65001 >nul
cd /d "%~dp0ai_mirror"
title Инвайт в чат

if not exist "invite_config.json" (
  echo Создайте invite_config.json из invite_config.example.json
  copy invite_config.example.json invite_config.json
  notepad invite_config.json
  pause
  exit /b 1
)

echo.
echo  Инвайт только в чат из invite_config.json
echo  VPN должен быть включён
echo.
python invite.py %*
pause
