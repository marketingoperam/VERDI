@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Задания: все 43 аккаунта; отчёты: половина (21) ===
python -u prepare_mirrors.py --config multi_config.verdi10_13.json --report-fraction 0.5
if errorlevel 1 exit /b 1

echo.
echo === Запуск клонера VERDI 10 + 13 ===
python -u run_pool.py --config multi_config.verdi10_13.json
