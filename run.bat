@echo off
rem Tag Print Assistant launcher. Uses 32-bit Python when installed (needed for the real green screen).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
py -3-32 -c "" >nul 2>&1
if %errorlevel%==0 (set PY=py -3-32) else (set PY=py -3)
%PY% -m tagbot %*
if errorlevel 1 pause
