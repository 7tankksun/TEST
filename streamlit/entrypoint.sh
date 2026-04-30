#!/bin/sh
set -e
cd /app
exec python3 -m streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8509 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --browser.gatherUsageStats false
