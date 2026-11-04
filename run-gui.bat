@echo off
setlocal
cd /d "%~dp0"
title DSIP Automated Discovery Tool
chcp 65001 >nul 2>&1
mode con: cols=92 lines=42
color 0B

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0splash.ps1" -Mode boot

echo.
echo    [*]  Locating Python runtime ...
python --version >nul 2>&1
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  Python was not found.
  echo         Install Python 3.12 or 3.13 from the Microsoft Store, then try again.
  echo         See docs\WINDOWS_11_NO_ADMIN_README.md
  echo.
  pause
  exit /b 1
)
echo    [OK] Python online.

echo    [*]  Loading PDF engine ^(pypdf^) ...
python -m pip install --disable-pip-version-check pypdf >nul 2>&1
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  Could not install pypdf. Check your network and try again.
  echo.
  pause
  exit /b 1
)
echo    [OK] PDF engine online.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0splash.ps1" -Mode open
if errorlevel 1 (
  echo    Opening DSIP GOV Portal Discovery Search Tool ...
)

python gui.py
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  The app exited with an error.
  echo.
  pause
)
exit /b 0
