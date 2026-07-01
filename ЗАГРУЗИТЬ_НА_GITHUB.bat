@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Авторизация GitHub (откроется браузер) ===
gh auth login -h github.com -p https -w
if errorlevel 1 (
  echo Ошибка авторизации. Повторите вручную: gh auth login
  pause
  exit /b 1
)

echo.
echo === Загрузка в https://github.com/marketingoperam/VERDI ===
git push -u origin main
if errorlevel 1 (
  echo Ошибка push.
  pause
  exit /b 1
)

echo.
echo Готово: https://github.com/marketingoperam/VERDI
pause
