@echo off
chcp 65001 >nul
cd /d "%~dp0Клонер чатов\ai_mirror"
title VERDI Cloner — прямой эфир

if not exist "..\shadowchat\sessions\listener_main.session" (
    echo Ошибка: нет listener_main.session
    echo Авторизуйте слушатель в shadowchat\sessions\
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" copy .env.example .env >nul
)

echo.
echo ========================================
echo   VERDI 7 + 10 + 13 — клонер в эфире
echo ========================================
echo   Конфиг: multi_config.verdi_all.json
echo   Остановка: Ctrl+C или закрыть окно
echo.
echo   Не запускайте второй экземпляр!
echo.

python -u run_pool.py --config multi_config.verdi_all.json
echo.
echo Клонер остановлен.
pause
