@echo off
REM Double-click this file to start the SPHEREx Sky Flip-book on this computer.
title SPHEREx Sky Flip-book
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages, this takes a few minutes...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python scripts\launch.py
if %errorlevel%==3 (
  timeout /t 4 >nul
  exit /b
)
echo.
echo The tool has stopped. If something went wrong, please send a screenshot of this window.
pause
