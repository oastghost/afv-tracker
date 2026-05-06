@echo off
setlocal enabledelayedexpansion
echo ============================================
echo  AFV Tracker - Build Script
echo ============================================
echo.

:: ── Locate Python (prefer venv) ───────────────────────────────────────────────
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)
echo Using Python: %PYTHON%
echo.

:: ── Timestamped release folder inside the repo ────────────────────────────────
:: Output goes to:  releases\YYYY-MM-DD_HHmm\
for /f "tokens=1-5 delims=/:. " %%a in ("%DATE% %TIME%") do (
    set YY=%%a
    set MM=%%b
    set DD=%%c
    set HH=%%d
    set MIN=%%e
)
:: Normalise single-digit hours (TIME can be " 9:..." on some locales)
set HH=%HH: =0%

set STAMP=%YY%-%MM%-%DD%_%HH%%MIN%
set RELEASE_DIR=releases\%STAMP%
set DIST_PATH=%RELEASE_DIR%\dist
set WORK_PATH=%RELEASE_DIR%\work

echo Release folder: %RELEASE_DIR%
echo.

:: ── 1. Install / upgrade PyInstaller ─────────────────────────────────────────
echo [1/3] Installing PyInstaller...
%PYTHON% -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is on your PATH.
    pause & exit /b 1
)

:: ── 2. Install project dependencies ──────────────────────────────────────────
echo [2/3] Installing project dependencies...
%PYTHON% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause & exit /b 1
)

:: ── 3. Build the exe ──────────────────────────────────────────────────────────
echo [3/3] Building AFV Tracker.exe...
%PYTHON% -m PyInstaller AFV_Tracker.spec --clean ^
    --distpath "%DIST_PATH%" ^
    --workpath "%WORK_PATH%"

if errorlevel 1 (
    echo ERROR: PyInstaller build failed. Check the output above.
    pause & exit /b 1
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ============================================
echo  Build complete!
echo.
echo  Executable:  %DIST_PATH%\AFV Tracker\AFV Tracker.exe
echo  Work files:  %WORK_PATH%\  (safe to delete)
echo ============================================
pause
endlocal
