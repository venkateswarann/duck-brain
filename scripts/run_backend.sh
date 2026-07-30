#!/usr/bin/env bash
# Backend only. For backend + frontend together use ./scripts/run.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

exec "$ROOT/scripts/run.sh" --backend-only "$@"
