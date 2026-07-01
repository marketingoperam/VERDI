@echo off
chcp 65001 >nul
:: Запускайте ПКМ -> Запуск от имени администратора

set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
set ENTRY=149.154.167.220 my.telegram.org

findstr /C:"my.telegram.org" "%HOSTS%" >nul
if %errorlevel%==0 (
    echo Строка my.telegram.org уже есть в hosts.
) else (
    echo.>>"%HOSTS%"
    echo %ENTRY%>>"%HOSTS%"
    echo Добавлено: %ENTRY%
)

echo.
echo Откройте https://my.telegram.org/apps в инкогнито
echo После получения api_id удалите строку через remove_telegram_hosts.bat
pause
