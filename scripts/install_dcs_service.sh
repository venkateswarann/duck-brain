#!/usr/bin/env bash
# Install the DCS backend as a systemd service on the robot (starts at boot).
#   sudo ./scripts/install_dcs_service.sh            # runs as the invoking user
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi
if [[ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]]; then
  echo "Backend venv missing; run ./scripts/setup_robot.sh first." >&2
  exit 1
fi

cat >/etc/systemd/system/dcs-backend.service <<EOF
[Unit]
Description=DCS (Duck Control System) backend on :8000
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=dialout audio gpio video
WorkingDirectory=$ROOT/backend
ExecStart=$ROOT/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
# Give the head servo loop priority over everything else on the Pi.
Nice=-5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dcs-backend.service >/dev/null
systemctl restart dcs-backend.service
echo "dcs-backend enabled. Logs: journalctl -fu dcs-backend"
