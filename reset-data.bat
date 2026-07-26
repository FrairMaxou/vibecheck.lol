@echo off
rem Double-click me: archives the current game data so you start fresh.
rem Nothing is deleted - old data goes to a timestamped backups folder.
cd /d "%~dp0"
echo This will archive your current kiffance data (games + ratings + log)
echo into a timestamped backup folder. The app starts fresh afterwards.
echo Quit the app first if it is running (tray icon ^> Quit).
echo.
set /p CONFIRM="Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo Cancelled - nothing was touched.
    pause
    exit /b
)
.venv\Scripts\python.exe tools\reset_data.py
echo.
pause
