@echo off
rem Double-click me: shows the "Had fun?" popup with fake data (no League needed).
cd /d "%~dp0"
.venv\Scripts\python.exe tools\preview_popup.py
pause
