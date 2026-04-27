@echo off
rem KOSPI, KOSDAQ, USA 순서로 run_local_export.py 실행 (배치 파일과 같은 폴더 기준)
rem 권장: py -3 -m pip install -r "%~dp0requirements_export.txt"
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PY=py -3"
set "ERR=0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo [%date% %time%] START run_all_export: KOSPI, KOSDAQ, USA
echo.

echo ========== KOSPI ==========
pushd "%~dp0kospi"
%PY% run_local_export.py
set "RC=!ERRORLEVEL!"
if !RC! neq 0 set ERR=1
echo OK: KOSPI - exit code !RC!
popd

echo.
echo ========== KOSDAQ ==========
pushd "%~dp0kosdaq"
%PY% run_local_export.py
set "RC=!ERRORLEVEL!"
if !RC! neq 0 set ERR=1
echo OK: KOSDAQ - exit code !RC!
popd

echo.
echo ========== USA ==========
pushd "%~dp0my_web_USA"
%PY% run_local_export.py
set "RC=!ERRORLEVEL!"
if !RC! neq 0 set ERR=1
echo OK: USA - exit code !RC!
popd

echo.
if !ERR! equ 0 (
  echo [%date% %time%] ALL OK
  endlocal & exit /b 0
)
echo [%date% %time%] FINISHED WITH ERRORS - see messages above
endlocal & exit /b 1
