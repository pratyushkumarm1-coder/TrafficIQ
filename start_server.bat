@echo off
REM TrafficIQ server starter / restarter
REM Usage:  start_server.bat   (or)   start_server.bat --restart
setlocal
cd /d "%~dp0"

REM kill existing backend python running our app
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *TrafficIQ*" >nul 2>&1

REM Find and stop our venv python running main.py (keep other pythons)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
  taskkill /F /PID %%p >nul 2>&1
)

ping -n 3 127.0.0.1 >nul

REM launch detached (survives this window closing)
start "TrafficIQ" /min cmd /c ""%CD%\backend\venv\Scripts\python.exe" "%CD%\backend\main.py" > "%CD%\backend\server_out.log" 2> "%CD%\backend\server_err.log""

echo.
echo TrafficIQ starting... verify at http://localhost:8000/dashboard
echo.
endlocal
