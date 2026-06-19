@echo off
REM Build script for UIATools executable
REM Run this from the UIATools root directory

echo ============================================
echo Building UIATools executable...
echo ============================================

REM Check if virtual environment exists and activate it
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Ensure PyInstaller is installed
echo Checking PyInstaller installation...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller>=6.0.0
)

REM Clean previous builds
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Build the executable
echo Building executable...
pyinstaller UIATools.spec --clean

if errorlevel 1 (
    echo ============================================
    echo BUILD FAILED!
    echo ============================================
    pause
    exit /b 1
)

echo ============================================
echo BUILD SUCCESSFUL!
echo Executable location: dist\UIATools.exe
echo ============================================

REM Show file size
for %%A in (dist\UIATools.exe) do echo File size: %%~zA bytes

pause
