#!/usr/bin/env bash
# One command on the laptop: find the robot, start the DCS UI against it (and
# optionally the Gemma brain), open the Duck page. Ctrl+C stops everything.
#
#   ./scripts/launch_duck.sh                 # UI only (camera, eyes, head, STOP)
#   ./scripts/launch_duck.sh --brain         # UI + Duck Brain (Gemma) + trace UI
#   ./scripts/launch_duck.sh --robot http://192.168.1.125:8000
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Pi 4 candidates, first that answers wins: LAN mDNS, Tailscale name.
ROBOTS=("http://rpi1.local:8000" "http://rpi1:8000")
WITH_BRAIN=0
BRAIN_SOURCE="robot"
UI_PORT=5173
OPEN_BROWSER=1

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Options:
  --robot URL        DCS backend on the Pi 4 (repeatable; default: ${ROBOTS[*]})
  --brain            also run the Duck Brain (needs Ollama with gemma3:4b)
  --brain-source S   robot | local | text (default: $BRAIN_SOURCE)
  --port N           UI port (default: $UI_PORT)
  --no-open          don't open a browser
EOF
}

CUSTOM_ROBOTS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --robot) CUSTOM_ROBOTS+=("$2"); shift 2 ;;
    --brain) WITH_BRAIN=1; shift ;;
    --brain-source) BRAIN_SOURCE="$2"; shift 2 ;;
    --port) UI_PORT="$2"; shift 2 ;;
    --no-open) OPEN_BROWSER=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
[[ ${#CUSTOM_ROBOTS[@]} -gt 0 ]] && ROBOTS=("${CUSTOM_ROBOTS[@]}")

ROBOT=""
for url in "${ROBOTS[@]}"; do
  if curl -sf -m 3 "$url/api/health" >/dev/null; then
    ROBOT="$url"
    break
  fi
done
if [[ -z "$ROBOT" ]]; then
  echo "No DCS backend answering at: ${ROBOTS[*]}" >&2
  echo "Is the Pi 4 on? Check: ssh rpi1 systemctl status dcs-backend" >&2
  exit 1
fi
echo "Robot: $ROBOT"
curl -s -m 3 "$ROBOT/api/companion/status" | python3 -c "$(cat <<'EOF'
import json, sys
s = json.load(sys.stdin)
ok = lambda v: "ok" if v else "--"
print("  head", ok(s["servos"]["ok"]), " eyes", ok(s["eyes"]["online"]), " mic", ok(s["audio"]["mic"]),
      " speaker", ok(s["audio"]["speaker"]), " camera", ok(s["camera"]["live"]))
EOF
)" 2>/dev/null || true

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Installing UI dependencies (first run)…"
  (cd "$ROOT/frontend" && npm install --silent)
fi

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

HOSTPORT="${ROBOT#*://}"
(
  cd "$ROOT/frontend"
  DCS_BACKEND_HOST="${HOSTPORT%%:*}" DCS_BACKEND_PORT="${HOSTPORT##*:}" \
    npx vite --host 127.0.0.1 --port "$UI_PORT" --strictPort 2>&1 | sed -u 's/^/[ui] /'
) &
PIDS+=($!)

if [[ "$WITH_BRAIN" -eq 1 ]]; then
  if ! command -v uv >/dev/null; then
    echo "--brain needs uv (https://docs.astral.sh/uv/)" >&2
    exit 1
  fi
  (
    cd "$ROOT/brain"
    uv run -q duck-brain --source "$BRAIN_SOURCE" --robot-url "$ROBOT" 2>&1 | sed -u 's/^/[brain] /'
  ) &
  PIDS+=($!)
fi

for _ in $(seq 1 40); do
  curl -sf -m 1 "http://127.0.0.1:$UI_PORT/" >/dev/null && break
  sleep 0.5
done
echo
echo "Duck page:  http://127.0.0.1:$UI_PORT/duck     (camera, eyes, head, STOP)"
[[ "$WITH_BRAIN" -eq 1 ]] && echo "Brain trace: http://127.0.0.1:8300"
echo "Ctrl+C stops everything."
if [[ "$OPEN_BROWSER" -eq 1 ]] && command -v xdg-open >/dev/null; then
  xdg-open "http://127.0.0.1:$UI_PORT/duck" >/dev/null 2>&1 || true
  [[ "$WITH_BRAIN" -eq 1 ]] && (sleep 8; xdg-open "http://127.0.0.1:8300" >/dev/null 2>&1 || true) &
fi
wait
