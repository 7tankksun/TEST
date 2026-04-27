@echo off
chcp 65001 >nul
rem api_hoard: 표(HTML) + 스냅샷 폴더
cd /d "%~dp0"
if not exist "data" (
  echo data 폴더 없음. 먼저: py -3 verify_and_store.py
  pause
  exit /b 1
)
if exist "data\catalog_table.html" start "" "data\catalog_table.html"
if exist "data\last_ok" start "" "data\last_ok"
if exist "data\manifest.json" start "" "data\manifest.json"
echo 열었습니다: catalog_table.html(표) / last_ok / manifest
pause
