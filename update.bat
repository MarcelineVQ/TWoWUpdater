@echo off
setlocal

:: TurtleWoW Updater - Double-click to update your game
:: Passes any arguments through, e.g.: update.bat check
:: Default command is "update" if none specified.

:: Run from the directory the bat file lives in
cd /d "%~dp0"

:: Find Python - try py launcher first (ships with python.org installer),
:: then python, then python3.

py -3 --version >nul 2>&1
if not errorlevel 1 goto :use_py

python --version 2>&1 | findstr /r "^Python 3\." >nul
if not errorlevel 1 goto :use_python

python3 --version >nul 2>&1
if not errorlevel 1 goto :use_python3

echo Python 3 was not found. Please install Python 3.10 or newer from:
echo https://www.python.org/downloads/
echo.
echo Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:use_py
set "PYTHON=py -3"
goto :run

:use_python
set "PYTHON=python"
goto :run

:use_python3
set "PYTHON=python3"
goto :run

:run
if "%~1"=="" (
    %PYTHON% twow_updater.py update
) else (
    %PYTHON% twow_updater.py %*
)

echo.
pause
