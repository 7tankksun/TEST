@echo off
cd /d "%~dp0"
node "scripts\fetch-it-news.mjs"
if errorlevel 1 (echo. & echo 실패: Node.js PATH 에 있는지 확인하세요. & pause)
