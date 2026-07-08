@echo off
chcp 65001 >nul
title VERDI Connector
cd /d "%~dp0"

if not exist ".env" copy .env.example .env

echo.
echo  VERDI Connector — запуск через Docker
echo  Панель откроется на http://localhost:3000
echo.

docker compose up --build
