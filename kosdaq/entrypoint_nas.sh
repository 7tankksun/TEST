#!/bin/sh
# /app 는 볼륨으로 덮일 수 있음 — 스크립트는 이미지 루트에 둠
set -e
if ! python -c "import flask" 2>/dev/null; then
  pip install --no-cache-dir "flask>=3.0"
fi
exec python /app/app_nas_serve_kosdaq.py
