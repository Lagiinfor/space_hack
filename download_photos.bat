@echo off
REM Double-click to download all SPHEREx photos for the five tour targets from NASA (about 4 to 15 minutes).
REM Not required: the app also fetches them by itself when needed. This just does it all up front.
title Download SPHEREx photos
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages, this takes a few minutes...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python scripts\download_photos.py
echo.
pause
