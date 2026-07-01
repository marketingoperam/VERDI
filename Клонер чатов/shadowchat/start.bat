@echo off
chcp 65001 >nul
title ShadowChat
cd /d "%~dp0"

echo.
echo  ========================================
echo           ShadowChat
echo  ========================================
echo.

:: Остановить старые процессы на порту 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

if not exist ".env" copy .env.example .env >nul

echo Устанавливаю зависимости...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo ОШИБКА: Python не найден или зависимости не установились.
    echo Установите Python с https://python.org и отметьте "Add to PATH"
    pause
    exit /b 1
)

echo.
python run.py
pause
