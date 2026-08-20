@echo off
REM Builds PZ SteamUploader Helper into a standalone Windows .exe.
REM Run this from the project root (the folder containing "py\").
REM Requires Python 3 + pip on Windows. PyInstaller does not cross-compile,
REM so this must be run on Windows, not Linux/macOS.
REM The exe is dropped directly into this root folder (next to config.json
REM and steamUploader\), so it shares those with "python py\app.py" runs.

setlocal

set APP_NAME=PZ SteamUploader Helper
set ENTRY=py\app.py
set DIST_DIR=.

echo Installing/upgrading PyInstaller...
python -m pip install --upgrade pyinstaller || goto :error

echo.
echo Building "%APP_NAME%.exe"...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    "%ENTRY%" || goto :error

echo.
echo Cleaning up PyInstaller work files...
if exist build rmdir /s /q build
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo.
echo Done. Your exe is at "%APP_NAME%.exe" in this folder.
echo It reads/writes the same config.json and steamUploader\ that
echo "python py\app.py" already uses.
goto :eof

:error
echo.
echo Build failed. See the error above.
exit /b 1
