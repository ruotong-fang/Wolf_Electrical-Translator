@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\EETranslator\EETranslator.exe" (
  echo Demo has not been built. Starting the Windows build now...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\build.ps1"
  if errorlevel 1 (
    echo.
    echo Build failed. Read the message above.
    pause
    exit /b 1
  )
)

start "" "dist\EETranslator\EETranslator.exe"
