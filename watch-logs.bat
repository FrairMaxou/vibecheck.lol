@echo off
rem Double-click me: streams the app log live (Ctrl+C to stop).
powershell -NoExit -Command "Get-Content \"$env:LOCALAPPDATA\LeagueOfKiffance\kiffance.log\" -Wait -Tail 30"
