#!/usr/bin/env bash
# DCS first-time / re-configure setup
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/configs/duck_config.json"
EXAMPLE="$ROOT/configs/duck_config.example.json"
VENV="$ROOT/backend/.venv"

NONINTERACTIVE=0
WITH_HARDWARE=0
WITH_FRONTEND=1
MOCK=1
SERIAL_PORT="/dev/ttyACM0"
ROBOT_ID="duck-mini-001"
ROBOT_NAME="Open Duck Mini"
POLL_HZ="15"
BOARD="rpi5"

usage() {
  cat <<EOF
DCS setup — install deps and write configs/duck_config.json

Usage: $(basename "$0") [options]

Options:
  -y, --yes              Non-interactive (use defaults / flags below)
  --hardware             Install optional ST3215 + OpenCV; set mock_hardware=false
  --mock                 Keep mock hardware (default)
  --no-frontend          Skip npm install
  --serial PORT          Serial device (default: /dev/ttyACM0)
  --robot-id ID          Robot id string
  --robot-name NAME      Display name
  --poll-hz N            Motor poll rate (default: 15)
  --board BOARD          Pinout board id: rpi5 | jetson_orin_nx (default: rpi5)
  -h, --help             Show this help

Examples:
  ./scripts/setup.sh -y
  ./scripts/setup.sh -y --hardware --serial /dev/ttyUSB0
  ./scripts/setup.sh                 # interactive prompts
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) NONINTERACTIVE=1; shift ;;
    --hardware) WITH_HARDWARE=1; MOCK=0; shift ;;
    --mock) MOCK=1; shift ;;
    --no-frontend) WITH_FRONTEND=0; shift ;;
    --serial) SERIAL_PORT="$2"; shift 2 ;;
    --robot-id) ROBOT_ID="$2"; shift 2 ;;
    --robot-name) ROBOT_NAME="$2"; shift 2 ;;
    --poll-hz) POLL_HZ="$2"; shift 2 ;;
    --board) BOARD="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

ask() {
  local prompt="$1" default="$2" var
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    echo "$default"
    return
  fi
  read -r -p "$prompt [$default]: " var
  echo "${var:-$default}"
}

ask_yn() {
  local prompt="$1" default="$2" var
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    [[ "$default" == "y" ]] && return 0 || return 1
  fi
  read -r -p "$prompt [y/N]: " var
  var="${var:-$default}"
  [[ "${var,,}" == "y" || "${var,,}" == "yes" ]]
}

echo "=== DCS setup ==="
echo "Root: $ROOT"
echo

if [[ "$NONINTERACTIVE" -eq 0 ]]; then
  ROBOT_ID="$(ask "Robot ID" "$ROBOT_ID")"
  ROBOT_NAME="$(ask "Robot name" "$ROBOT_NAME")"
  SERIAL_PORT="$(ask "Servo serial port" "$SERIAL_PORT")"
  POLL_HZ="$(ask "Motor poll Hz" "$POLL_HZ")"
  BOARD="$(ask "Board profile (rpi5 / jetson_orin_nx)" "$BOARD")"
  if ask_yn "Use real hardware (ST3215 + camera)?" "n"; then
    WITH_HARDWARE=1
    MOCK=0
  else
    MOCK=1
  fi
  if ask_yn "Install frontend npm packages?" "y"; then
    WITH_FRONTEND=1
  else
    WITH_FRONTEND=0
  fi
fi

echo
echo "--- Python backend ---"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$ROOT/backend/requirements.txt"
if [[ "$WITH_HARDWARE" -eq 1 ]]; then
  echo "Installing optional hardware packages (st3215, opencv)…"
  pip install -q st3215 opencv-python-headless || {
    echo "Warning: optional hardware packages failed; continuing with core deps."
  }
fi

echo
echo "--- Config ---"
if [[ ! -f "$CONFIG" ]]; then
  cp "$EXAMPLE" "$CONFIG"
  echo "Created $CONFIG from example"
else
  echo "Updating existing $CONFIG"
fi

python3 - <<PY
import json
from pathlib import Path

path = Path("$CONFIG")
data = json.loads(path.read_text())
data["robot_id"] = "$ROBOT_ID"
data["robot_name"] = "$ROBOT_NAME"
data["serial_port"] = "$SERIAL_PORT"
data["poll_hz"] = float("$POLL_HZ")
data["mock_hardware"] = bool($MOCK)
path.write_text(json.dumps(data, indent=2) + "\n")
print(f"  robot_id={data['robot_id']}")
print(f"  mock_hardware={data['mock_hardware']}")
print(f"  serial_port={data['serial_port']}")
print(f"  poll_hz={data['poll_hz']}")
PY

PINOUT="$ROOT/configs/pinout_schema.json"
if [[ ! -f "$PINOUT" ]]; then
  cat > "$PINOUT" <<EOF
{
  "schema_version": 1,
  "board": "$BOARD",
  "devices": []
}
EOF
  echo "Created $PINOUT (board=$BOARD)"
else
  python3 - <<PY
import json
from pathlib import Path
p = Path("$PINOUT")
d = json.loads(p.read_text())
d["board"] = "$BOARD"
p.write_text(json.dumps(d, indent=2) + "\n")
print(f"Updated pinout board=$BOARD")
PY
fi

if [[ "$WITH_FRONTEND" -eq 1 ]]; then
  echo
  echo "--- Frontend ---"
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found — skip frontend. Install Node.js then: cd frontend && npm install"
  else
    (cd "$ROOT/frontend" && npm install)
  fi
fi

cat <<EOF

=== Setup complete ===

Start backend:
  cd $ROOT/backend && source .venv/bin/activate
  uvicorn app.main:app --host 0.0.0.0 --port 8000

Start frontend:
  cd $ROOT/frontend && npm run dev

Open UI:  http://127.0.0.1:5173
Help/Setup page: http://127.0.0.1:5173/help
API docs: http://127.0.0.1:8000/docs

Tip: use the in-app Help page to edit parameters with explanations.
EOF
