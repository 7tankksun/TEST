@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
py -3 -X utf8 "%~dp0scheduled_ohlcv_collector.py" %*
