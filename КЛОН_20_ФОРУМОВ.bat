@echo off

chcp 65001 >nul

cd /d "%~dp0Клонер чатов\ai_mirror"

title Клон 20 форумов multi12000

echo.

echo  Создание 20 копий @multi12000

echo  VPN должен быть включён

echo  Прогресс: forum_clones_batch.json

echo.

python -u clone_forum_batch.py --count 20 %*

pause

