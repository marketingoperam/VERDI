@echo off
chcp 65001 >nul
:: Запускайте ПКМ -> Запуск от имени администратора

set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
powershell -NoProfile -Command "(Get-Content '%HOSTS%') | Where-Object { $_ -notmatch 'my\.telegram\.org' } | Set-Content '%HOSTS%' -Encoding ASCII"
echo Строки с my.telegram.org удалены из hosts.
pause
