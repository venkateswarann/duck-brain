#!/usr/bin/env bash
# Deploy DCS backend to the robot (no frontend, real hardware).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<EOF
Usage: $(basename "$0") [extra setup.sh options]

Installs the DCS backend on the robot without the frontend, and enables
real hardware (mock_hardware=false). Extra args are forwarded to setup.sh.

Examples:
  $(basename "$0")
  $(basename "$0") --serial /dev/ttyACM0
  $(basename "$0") -y
EOF
  exit 0
fi

"$ROOT/scripts/setup.sh" --no-frontend --hardware "$@"

cat <<EOF

=== Robot backend deployed ===
Start:  ./scripts/run.sh --backend-only
The API will be at http://<robot-ip>:8000

On your PC, run:
  ./scripts/run_frontend.sh --backend-url http://<robot-ip>:8000
EOF
