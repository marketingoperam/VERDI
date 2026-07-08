@echo off
chcp 65001 >nul
title VERDI Connector (local)
cd /d "%~dp0"

echo.
echo  VERDI Connector — локальный запуск (без Docker)
echo  Панель: http://127.0.0.1:3000
echo.

cd apps\api
if not exist .env copy .env.example .env 2>nul
if not exist .env (
  echo DATABASE_URL=file:./dev.db> .env
  echo USE_SYNC_OUTBOX=true>> .env
  echo JWT_SECRET=local-dev-secret>> .env
  echo PORT=3001>> .env
  echo CORS_ORIGIN=http://127.0.0.1:3000>> .env
)

echo [1/4] API dependencies...
call npm install
if errorlevel 1 goto :error

echo [2/4] Database...
call npx prisma generate
call npx prisma db push
if errorlevel 1 goto :error

echo [3/4] Starting API on :3001...
start "VERDI API" cmd /k "npm run start:dev"

cd ..\web
echo [4/4] Web dependencies + panel on :3000...
call npm install
if errorlevel 1 goto :error

start "VERDI Web" cmd /k "set NEXT_PUBLIC_API_URL=http://127.0.0.1:3001&& set NEXT_PUBLIC_WS_URL=http://127.0.0.1:3001&& npx next dev -p 3000 -H 127.0.0.1"

echo.
echo  Готово. Откройте http://127.0.0.1:3000
echo  Логин: andf1n@verdi.local / admin123
echo.
pause
goto :eof

:error
echo.
echo Ошибка запуска. Убедитесь что установлен Node.js 20+
pause
