#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Starting DCS backend on :8000 ..."
cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
