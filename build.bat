@echo off
echo ============================================
echo  AFV Tracker - Build Script
echo ============================================
echo.

:: Locate Python — prefer the venv if it exists
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
    set PIP=.venv\Scripts\pip.exe
    set PYINSTALLER=.venv\Scripts\pyinstaller.exe
) else (
    set PYTHON=python
    set PIP=pip
    set PYINSTALLER=pyinstaller
)

echo Using Python: %PYTHON%
echo.

:: Install/upgrade PyInstaller into the correct environment
echo [1/3] Installing PyInstaller...
%PYTHON% -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is on your PATH.
    pause
    exit /b 1
)

:: Install all project dependencies
echo [2/3] Installing project dependencies...
%PYTHON% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
)

:: Build the exe — call pyinstaller via python -m to guarantee the right env
echo [3/3] Building AFV Tracker.exe...
%PYTHON% -m PyInstaller AFV_Tracker.spec --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Done!  Executable is in:  dist\AFV Tracker\AFV Tracker.exe
echo ============================================
pause
