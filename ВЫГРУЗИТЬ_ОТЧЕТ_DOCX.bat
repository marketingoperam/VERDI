@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
pip install python-docx -q
echo === Формирование полного отчёта DOCX ===
python scripts\export_docx.py
echo.
echo Отчёт сохранён в папку output\
pause
