@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%~dp0"

rem c:\code\.venv 글로벌 가상환경 사용 (py -3 는 fallback)
if exist "c:\code\.venv\Scripts\python.exe" (
  set "PY=c:\code\.venv\Scripts\python.exe"
) else (
  set "PY=py -3"
)

echo [Python] %PY%
echo [시작] Streamlit 앱을 실행합니다...
"%PY%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8509
