#!/bin/bash
set -e

echo "────────────────────────────────────────"
echo "  School AI Platform – Backend Starting"
echo "────────────────────────────────────────"

echo "[1/2] Running Alembic migrations..."
alembic upgrade head
echo "      Migrations complete."

echo "[2/2] Starting FastAPI server..."
exec uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --loop uvloop \
  --http httptools
