@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\build.ps1"
if errorlevel 1 (
  echo.
  echo Release build failed. Read the message above.
  pause
  exit /b 1
)

echo.
echo Final customer installer:
echo installer-output\Wolf-Electrical-Translator-Setup-0.2.0.exe
pause
