#!/usr/bin/env bash
# Deploy the head services (eyes, head camera, boot status) to the Pi Zero 2 W.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="bdxmini.local"
USER_NAME=""
DEST_NAME="duck-head"
# Wi-Fi/Tailscale addresses of the Pi 4, used by the camera if the USB link is down.
DCS_FALLBACK="http://rpi1.local:8000 http://rpi1:8000"
INSTALL=1

usage() {
  cat <<EOF
Usage: $(basename "$0") [--host HOST] [--user USER] [--dcs-fallback URL] [--no-install]

Copies devices/head_zero/ (plus robot_scripts/dcs_sdk.py) to ~/$DEST_NAME on the
Zero, installs apt/pip packages, and enables duck-boot-status.service, which
hands over to duck-eyes.service (and duck-headcam.service) once the robot is ready.

  --host          SSH host of the Zero (default: $HOST; a Tailscale name works too)
  --user          SSH user (default: your ssh config / current user)
  --dcs-fallback  space-separated DCS URLs for the camera if the USB link is
                  down (default: "$DCS_FALLBACK")
  --no-install    copy files and restart services only (fast redeploy)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --dcs-fallback) DCS_FALLBACK="$2"; shift 2 ;;
    --no-install) INSTALL=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

TARGET="${USER_NAME:+$USER_NAME@}$HOST"
echo "--- Copying head services to $TARGET:~/$DEST_NAME ---"
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.png' \
  "$ROOT/devices/head_zero/" "$TARGET:$DEST_NAME/"
rsync -az "$ROOT/robot_scripts/dcs_sdk.py" "$TARGET:$DEST_NAME/dcs_sdk.py"

# shellcheck disable=SC2087  # expand locally on purpose: INSTALL and DCS_FALLBACK
ssh "$TARGET" bash -s <<EOF
set -euo pipefail
DIR="\$HOME/$DEST_NAME"
cd "\$DIR"
if [[ "$INSTALL" -eq 1 ]]; then
  echo "--- apt packages (only what's missing; the Zero's SD card is small) ---"
  missing=()
  for pkg in python3-venv python3-pil python3-numpy python3-spidev python3-rpi.gpio \
             python3-picamera2 fonts-dejavu-core; do
    dpkg -s "\$pkg" >/dev/null 2>&1 || missing+=("\$pkg")
  done
  # rpicam-apps and rpicam-apps-lite conflict: keep whichever is installed.
  dpkg -s rpicam-apps >/dev/null 2>&1 || dpkg -s rpicam-apps-lite >/dev/null 2>&1 || missing+=(rpicam-apps-lite)
  if [[ \${#missing[@]} -gt 0 ]]; then
    echo "installing: \${missing[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq --no-install-recommends "\${missing[@]}" >/dev/null
  else
    echo "all present"
  fi
  if ! grep -qs '^dtparam=spi=on' /boot/firmware/config.txt; then
    echo "Enabling SPI (takes effect after reboot)"
    echo 'dtparam=spi=on' | sudo tee -a /boot/firmware/config.txt >/dev/null
  fi
  echo "--- python venv (system site packages for picamera2/spidev) ---"
  [[ -d .venv ]] || python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -q --no-cache-dir fastapi 'uvicorn>=0.30'
fi

echo "--- systemd units ---"
for unit in systemd/*.service; do
  sed -e "s#@DIR@#\$DIR#g" -e "s#@USER@#\$(id -un)#g" -e "s#@DCS_FALLBACK@#$DCS_FALLBACK#g" \
    "\$unit" | sudo tee "/etc/systemd/system/\$(basename "\$unit")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable duck-boot-status.service >/dev/null
sudo rm -f /run/duck-boot-status.failures
sudo systemctl stop duck-headcam.service duck-eyes.service 2>/dev/null || true
sudo systemctl restart duck-boot-status.service
echo "Deployed. Watch: journalctl -fu duck-boot-status -u duck-eyes -u duck-headcam"
EOF
