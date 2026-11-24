#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "No .venv found — run ./setup.sh first."
  exit 1
fi
source .venv/bin/activate
echo "Starting ClassForge at http://127.0.0.1:8080"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
