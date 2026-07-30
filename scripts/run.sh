#!/usr/bin/env bash
# Launch DCS backend (FastAPI) and frontend (Vite) together.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

BACKEND_HOST="0.0.0.0"
BACKEND_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
RUN_BACKEND=1
RUN_FRONTEND=1
RELOAD=0

usage() {
  cat <<EOF
DCS launcher — starts backend and frontend together

Usage: $(basename "$0") [options]

Options:
  --backend-only          Start only the FastAPI backend
  --frontend-only         Start only the Vite frontend
  --host HOST             Backend bind host (default: $BACKEND_HOST)
  --port PORT             Backend port (default: $BACKEND_PORT)
  --frontend-port PORT    Frontend port (default: $FRONTEND_PORT)
  --reload                Run uvicorn with --reload (development)
  -h, --help              Show this help

Both services stop together on Ctrl+C.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only) RUN_FRONTEND=0; shift ;;
    --frontend-only) RUN_BACKEND=0; shift ;;
    --host) BACKEND_HOST="$2"; shift 2 ;;
    --port) BACKEND_PORT="$2"; shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    --reload) RELOAD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# 0.0.0.0 is a bind address, not a connect address — the proxy must dial loopback.
PROXY_HOST="$BACKEND_HOST"
[[ "$PROXY_HOST" == "0.0.0.0" || "$PROXY_HOST" == "::" ]] && PROXY_HOST="127.0.0.1"

BACKEND_PGID=""
FRONTEND_PGID=""

cleanup() {
  trap - INT TERM EXIT
  local stopped=0
  for pgid in "$FRONTEND_PGID" "$BACKEND_PGID"; do
    [[ -z "$pgid" ]] && continue
    # Job control gives each service its own process group, so one signal
    # reaches the wrapper subshell, the server, and the log prefixer.
    kill -TERM -"$pgid" 2>/dev/null || true
    stopped=1
  done
  wait 2>/dev/null || true
  # Stay quiet when we bailed out during pre-flight checks and started nothing.
  [[ "$stopped" -eq 1 ]] && printf '\nDCS stopped.\n'
}
trap cleanup INT TERM EXIT

port_busy() {
  local port="$1"
  command -v ss >/dev/null 2>&1 || return 1
  ss -ltn 2>/dev/null | grep -q ":${port} "
}

# Starting Vite before the backend answers floods the log with proxy ECONNREFUSED errors.
wait_for_backend() {
  echo "Waiting for backend on ${PROXY_HOST}:${BACKEND_PORT} ..."
  for _ in $(seq 1 60); do
    if curl -fsS -m 1 "http://${PROXY_HOST}:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
      echo "Backend is up."
      return 0
    fi
    if ! kill -0 "-${BACKEND_PGID}" 2>/dev/null; then
      echo "Backend exited during startup — see [backend] output above." >&2
      exit 1
    fi
    sleep 0.5
  done
  echo "Backend not ready after 30s; starting frontend anyway." >&2
}

if [[ "$RUN_BACKEND" -eq 1 ]]; then
  if [[ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]]; then
    echo "Backend venv missing. Run ./scripts/setup.sh first." >&2
    exit 1
  fi
  if port_busy "$BACKEND_PORT"; then
    echo "Port $BACKEND_PORT is already in use — is another backend running?" >&2
    exit 1
  fi
fi

if [[ "$RUN_FRONTEND" -eq 1 ]]; then
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "Frontend deps missing. Run: cd frontend && npm install" >&2
    exit 1
  fi
  if port_busy "$FRONTEND_PORT"; then
    echo "Port $FRONTEND_PORT is already in use — is another Vite dev server running?" >&2
    exit 1
  fi
fi

if [[ "$RUN_BACKEND" -eq 0 && "$RUN_FRONTEND" -eq 0 ]]; then
  echo "Nothing to start." >&2
  exit 1
fi

# Job control puts each background job in its own process group, which is what
# makes the group-wide kill in cleanup() work.
set -m

if [[ "$RUN_BACKEND" -eq 1 ]]; then
  echo "Starting backend on http://${BACKEND_HOST}:${BACKEND_PORT} ..."
  UVICORN_ARGS=(app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT")
  [[ "$RELOAD" -eq 1 ]] && UVICORN_ARGS+=(--reload)
  (
    cd "$ROOT/backend"
    # Inherited by scripts launched from the Scripts page so dcs_sdk can reach
    # this backend (e.g. to publish video frames).
    export DCS_BACKEND_PORT="$BACKEND_PORT"
    export DCS_API_URL="http://127.0.0.1:${BACKEND_PORT}"
    .venv/bin/uvicorn "${UVICORN_ARGS[@]}" 2>&1 | sed -u 's/^/[backend] /'
  ) &
  BACKEND_PGID="$!"
fi

if [[ "$RUN_FRONTEND" -eq 1 ]]; then
  [[ "$RUN_BACKEND" -eq 1 ]] && wait_for_backend
  echo "Starting frontend on http://${FRONTEND_HOST}:${FRONTEND_PORT} ..."
  (
    cd "$ROOT/frontend"
    # Read by vite.config.ts to aim the /api, /ws and /stream proxies at the backend.
    export DCS_BACKEND_HOST="$PROXY_HOST"
    export DCS_BACKEND_PORT="$BACKEND_PORT"
    npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" 2>&1 \
      | sed -u 's/^/[frontend] /'
  ) &
  FRONTEND_PGID="$!"
fi

set +m

cat <<EOF

DCS is running.
EOF
[[ "$RUN_FRONTEND" -eq 1 ]] && cat <<EOF
  UI:        http://${FRONTEND_HOST}:${FRONTEND_PORT}
  Help page: http://${FRONTEND_HOST}:${FRONTEND_PORT}/help
EOF
[[ "$RUN_BACKEND" -eq 1 ]] && cat <<EOF
  API docs:  http://${PROXY_HOST}:${BACKEND_PORT}/docs
EOF
cat <<EOF

Press Ctrl+C to stop.

EOF

# Return as soon as either service dies so a crash is noticed immediately.
wait -n
