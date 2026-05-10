@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
py -3 -X utf8 "%~dp0fast_stage2_validator.py" --cache-dir "%~dp0tema_cache_data\\cache" --out-dir "%~dp0tema_stage2_data" %*
