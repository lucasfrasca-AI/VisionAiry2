#!/usr/bin/env bash
cd "$(dirname "$0")/.."
if lsof -i :8000 > /dev/null 2>&1; then
  echo "Error: port 8000 is already in use. Stop the other service first."
  exit 1
fi
uv run uvicorn src.dashboard.app:app --host 127.0.0.1 --port 8000 --reload
