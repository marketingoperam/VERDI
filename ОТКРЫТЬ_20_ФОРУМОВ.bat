@echo off

chcp 65001 >nul

cd /d "%~dp0Клонер чатов\ai_mirror"

title Публичные теги multiverdichat

echo.

echo  Открыть 20 копий + username multiverdichat1..20

echo.

python -u open_forum_clones.py %*

pause

