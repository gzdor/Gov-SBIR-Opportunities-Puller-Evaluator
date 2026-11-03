@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.12 or 3.13 from the Microsoft Store, then try again.
  echo See docs\WINDOWS_11_NO_ADMIN_README.md
  pause
  exit /b 1
)

echo Installing PDF reader if needed...
python -m pip install --disable-pip-version-check pypdf
if errorlevel 1 (
  echo Could not install pypdf. Check your network and try again.
  pause
  exit /b 1
)

echo Starting to Open the GUI...
echo Opening DSIP GOV Portal Discovery Search Tool ...
python gui.py
if errorlevel 1 (
  echo The app exited with an error.
  pause
)
