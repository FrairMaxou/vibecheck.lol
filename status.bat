@echo off
rem Double-click me: shows capture status (connection, games, ratings).
cd /d "%~dp0"
.venv\Scripts\python.exe tools\status.py
echo.
pause
