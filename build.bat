@echo off
echo ============================================
echo  AFV Tracker - Build Script
echo ============================================
echo.

:: Install/upgrade PyInstaller
echo [1/3] Installing PyInstaller...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python and pip are on your PATH.
    pause
    exit /b 1
)

:: Install all project dependencies
echo [2/3] Installing project dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
)

:: Build the exe
echo [3/3] Building AFV Tracker.exe...
pyinstaller AFV_Tracker.spec --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Done!  Executable is in:  dist\AFV Tracker.exe
echo ============================================
pause
