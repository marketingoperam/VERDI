@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Установка ===
pip install -r requirements.txt -q
echo.
python run_all.py
