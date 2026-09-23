@echo off
rem Starts the Werkbank engine and opens http://127.0.0.1:8765 (DESIGN.md section 6.4).
rem Close this window to stop the engine. Keep this file ASCII-only.
setlocal
cd /d "%~dp0.."
title Werkbank engine

rem Folders where winget and uv put their programs; a PATH inherited from before the
rem installer ran may not include them yet.
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 goto no_uv

rem --no-sync: the installer syncs the environment; syncing here would undo a yt-dlp update.
uv run --project engine --no-sync werkbank-engine --open %*
if errorlevel 1 goto failed
exit /b 0

:no_uv
echo uv was not found. Run the installer first:
echo     powershell -ExecutionPolicy Bypass -File scripts\install.ps1
pause
exit /b 1

:failed
echo.
echo The Werkbank engine stopped with an error (see above).
pause
exit /b 1
