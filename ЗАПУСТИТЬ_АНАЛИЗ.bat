@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
echo === AI-анализ находок (Gonka) ===
python scripts\run_ai_analysis.py
pause
