@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "data\catalog_table.html" (
  start "" "data\catalog_table.html"
) else (
  echo data\catalog_table.html 이 없습니다. 먼저 py -3 render_catalog_table.py
  pause
)
