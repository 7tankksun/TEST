#!/bin/sh
set -e
if ! python -c "import flask" 2>/dev/null; then
  pip install --no-cache-dir "flask>=3.0"
fi
exec python /app/app_nas_serve_usa.py
