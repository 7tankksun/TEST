@echo off
setlocal
cd /d "%~dp0"
py -3 "%~dp0run_portal_batch.py" %*
set EC=%ERRORLEVEL%
echo.
echo exit code %EC%
exit /b %EC%
