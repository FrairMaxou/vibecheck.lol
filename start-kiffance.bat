@echo off
rem Double-click me: starts League of Kiffance in the system tray (no console window).
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe -m kiffance
