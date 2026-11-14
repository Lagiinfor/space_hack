@echo off
REM Double-click this file to start the SPHEREx Sky Flip-book on this computer.
title SPHEREx Sky Flip-book
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python, this takes a few minutes...
  python -m venv .venv
)
REM (Re)install the add-ons if this is the first run, a previous install failed,
REM or requirements.txt changed after an update.
fc /b requirements.txt .venv\installed-requirements.txt >nul 2>&1
if errorlevel 1 (
  echo Installing or updating Python add-ons...
  .venv\Scripts\python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Installing the add-ons failed. Check the internet connection and double-click start.bat again.
    pause
    exit /b 1
  )
  copy /y requirements.txt .venv\installed-requirements.txt >nul
)
.venv\Scripts\python scripts\launch.py
if %errorlevel%==3 (
  timeout /t 4 >nul
  exit /b
)
echo.
echo The tool has stopped. If something went wrong, please send a screenshot of this window.
pause
