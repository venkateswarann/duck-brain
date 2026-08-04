#!/usr/bin/env bash
# Run DCS frontend, connecting to a remote backend (e.g. on the robot).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

BACKEND_URL=""
FRONTEND_HOST="0.0.0.0"
FRONTEND_PORT="5173"

usage() {
  cat <<EOF
Usage: $(basename "$0") --backend-url http://<robot-ip>:8000 [options]

Options:
  --backend-url URL   Backend base URL (required), e.g. http://10.9.9.45:8000
  --host HOST         Frontend bind host (default: $FRONTEND_HOST)
  --port PORT         Frontend port (default: $FRONTEND_PORT)
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url) BACKEND_URL="$2"; shift 2 ;;
    --host) FRONTEND_HOST="$2"; shift 2 ;;
    --port) FRONTEND_PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$BACKEND_URL" ]]; then
  usage >&2
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Frontend deps missing. Run: ./scripts/setup_frontend.sh" >&2
  exit 1
fi

# Parse host:port from URL for the Vite proxy (vite.config.ts).
REST="${BACKEND_URL#http://}"
REST="${REST#https://}"
REST="${REST%%/*}"
BACKEND_HOST="${REST%%:*}"
if [[ "$REST" == *:* ]]; then
  BACKEND_PORT="${REST##*:}"
else
  BACKEND_PORT="8000"
fi

echo "Frontend → Backend at $BACKEND_URL ($BACKEND_HOST:$BACKEND_PORT)"
cd "$ROOT/frontend"
export DCS_BACKEND_HOST="$BACKEND_HOST"
export DCS_BACKEND_PORT="$BACKEND_PORT"
exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
