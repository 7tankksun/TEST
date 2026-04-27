@echo off
setlocal

cd /d "c:\code\SynologyDrive\local"

rem Optional tuning for export payload
set "MAX_TREND_CHARTS=50"
set "TOP_SUMMARY_ROWS=50"

rem Uncomment and set if you want a custom output directory
rem set "EXPORT_DIR=c:\code\SynologyDrive\local\nas_web_payload"

python "run_local_export.py" >> "c:\code\SynologyDrive\local\export.log" 2>&1

endlocal
