#!/usr/bin/env bash
# Set up DCS frontend on your PC (no backend, no Python).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<EOF
Usage: $(basename "$0")

Installs npm dependencies for the DCS frontend only. Use this on a PC
that will talk to a backend running on the robot.
EOF
  exit 0
fi

echo "=== DCS frontend setup ==="
if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Install Node.js first." >&2
  exit 1
fi
(cd "$ROOT/frontend" && npm install)

cat <<EOF

=== Frontend ready ===
Run:  ./scripts/run_frontend.sh --backend-url http://<robot-ip>:8000
EOF
