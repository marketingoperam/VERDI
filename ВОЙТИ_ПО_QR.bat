@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
set PYTHONPATH=%CD%\..\\backend;%CD%\..
pip install qrcode[pil] -q
echo === Вход по QR-коду (без SMS) ===
python scripts\telegram_qr_login.py
pause
