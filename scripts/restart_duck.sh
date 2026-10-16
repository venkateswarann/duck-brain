#!/usr/bin/env bash
# Full restart of the duck from the laptop, then wait until everything is healthy.
#
#   ./scripts/restart_duck.sh              # restart all services (laptop, Pi 4, head Zero)
#   ./scripts/restart_duck.sh --reboot     # reboot both Pis instead (power-cycle-like)
#   ./scripts/restart_duck.sh --brain      # ...and start the UI + brain afterwards
#
# Restarting services does not move the head: head.control soft-starts from the
# present pose. Ears stay limp until their first command.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PI4=rpi1              # ssh host of the Pi 4 (DCS)
ZERO=bdxmini          # ssh host of the head Pi Zero
ZERO_USB=10.55.0.2    # the Zero over the Pi 4's USB link (fallback via ssh -J)
DCS_URL=""            # default: http://$PI4.local:8000, then http://$PI4:8000
REBOOT=0
LAUNCH=()
WAIT_S=240

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Options:
  --reboot          reboot the Zero and the Pi 4 instead of restarting services
  --brain           afterwards run ./scripts/launch_duck.sh --brain (extra args after --)
  --ui              afterwards run ./scripts/launch_duck.sh (UI only)
  --pi4 HOST        ssh host of the Pi 4 (default: $PI4)
  --zero HOST       ssh host of the head Zero (default: $ZERO)
  --wait SECONDS    how long to wait for everything to come up (default: $WAIT_S)
  Anything after -- is passed to launch_duck.sh, e.g. --brain -- --no-tracking
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reboot) REBOOT=1; shift ;;
    --brain) LAUNCH=(--brain); shift ;;
    --ui) LAUNCH=(); LAUNCH_UI=1; shift ;;
    --pi4) PI4="$2"; shift 2 ;;
    --zero) ZERO="$2"; shift 2 ;;
    --wait) WAIT_S="$2"; shift 2 ;;
    --) shift; LAUNCH+=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

SSH=(ssh -o ConnectTimeout=6 -o BatchMode=yes)
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
ok() { printf '  \033[32mok\033[0m  %s\n' "$*"; }
bad() { printf '  \033[31m!!\033[0m  %s\n' "$*"; }

# Run a command on the Zero: directly (Wi-Fi/Tailscale) or through the Pi 4's USB link.
zero_ssh() {
  "${SSH[@]}" "$ZERO" "$@" 2>/dev/null && return 0
  "${SSH[@]}" -J "$PI4" "$(id -un)@$ZERO_USB" "$@" 2>/dev/null
}

find_dcs() {
  for url in ${DCS_URL:-"http://$PI4.local:8000" "http://$PI4:8000"}; do
    curl -sf -m 3 "$url/api/health" >/dev/null && { echo "$url"; return 0; }
  done
  return 1
}

# ------------------------------------------------------------------ 1. laptop
say "Laptop: stopping the brain and UI"
pkill -f 'bin/duck-brain' 2>/dev/null && ok "brain stopped" || ok "no brain running"
for port in 5173 8300; do fuser -k "$port/tcp" >/dev/null 2>&1 && ok "freed port $port"; done

# ------------------------------------------------------------------ 2. the Pis
if [[ "$REBOOT" -eq 1 ]]; then
  # Zero first (it is powered from the Pi 4), then the Pi 4.
  say "Rebooting the head Zero ($ZERO)"
  zero_ssh 'sudo systemctl reboot' && ok "reboot sent" || bad "Zero not reachable (it reboots with the Pi 4 anyway)"
  sleep 2
  say "Rebooting the Pi 4 ($PI4)"
  "${SSH[@]}" "$PI4" 'sudo systemctl reboot' 2>/dev/null && ok "reboot sent" || bad "Pi 4 not reachable: check its power"
  sleep 15
else
  say "Pi 4 ($PI4): restarting DCS"
  if "${SSH[@]}" "$PI4" 'sudo systemctl restart dcs-backend' 2>/dev/null; then ok "dcs-backend restarted"
  else bad "Pi 4 not reachable: check its power, or use --reboot after it is back"; fi
  say "Head Zero ($ZERO): restarting eyes, ears, lamp and camera"
  # duck-boot-status shows progress on the eyes, then hands over to duck-eyes (which pulls in duck-headcam).
  if zero_ssh 'sudo rm -f /run/duck-boot-status.failures; sudo systemctl stop duck-eyes duck-headcam; sudo systemctl restart duck-boot-status'; then
    ok "head services restarted"
  else bad "Zero not reachable"; fi
fi

# ------------------------------------------------------------------ 3. wait for health
say "Waiting for the duck (up to ${WAIT_S}s)"
deadline=$((SECONDS + WAIT_S))
URL=""
STATUS=""
while (( SECONDS < deadline )); do
  URL="${URL:-$(find_dcs || true)}"
  if [[ -n "$URL" ]]; then
    STATUS="$(curl -sf -m 4 "$URL/api/companion/status" || true)"
    if [[ -n "$STATUS" ]] && python3 - "$STATUS" <<'EOF'
import json, sys
s = json.loads(sys.argv[1])
ready = s["eyes"]["online"] and s["camera"]["live"] and s["audio"]["speaker"]
sys.exit(0 if ready else 1)
EOF
    then break; fi
  fi
  printf '.'
  sleep 3
done
echo

if [[ -z "$STATUS" ]]; then
  bad "DCS never answered. Check: ssh $PI4 'journalctl -u dcs-backend -n 50'"
  exit 1
fi

python3 - "$STATUS" "$URL" <<'EOF'
import json, sys
s, url = json.loads(sys.argv[1]), sys.argv[2]
def line(good, name, detail=""):
    mark = "\033[32mok\033[0m" if good else "\033[31m!!\033[0m"
    print(f"  {mark}  {name:<8} {detail}")
print(f"  DCS at {url}")
sv = s["servos"]
line(sv["ok"], "head", f"{sv.get('found', 0)}/4 servos" + (" (MOCK: servo power off?)" if sv.get("mock") else ""))
e = s["eyes"]
line(e["online"], "eyes", e.get("url") or "offline")
ears = s.get("ears", {})
line(ears.get("ok", False), "ears", f"{ears.get('driver')} {'; '.join(ears.get('errors', []))}")
lamp = s.get("lamp", {})
line(lamp.get("ok", False), "lamp", lamp.get("error") or ("on" if lamp.get("on") else "off"))
a = s["audio"]
line(a.get("mic"), "mic")
line(a.get("speaker"), "speaker")
line(s["camera"]["live"], "camera", s["camera"]["stream"])
EOF

say "Power"
for host in "$PI4" "$ZERO"; do
  if [[ "$host" == "$ZERO" ]]; then t="$(zero_ssh 'vcgencmd get_throttled' || true)"; else t="$("${SSH[@]}" "$host" 'vcgencmd get_throttled' 2>/dev/null || true)"; fi
  t="${t#throttled=}"
  if [[ -z "$t" ]]; then bad "$host: unreachable"
  elif [[ "$t" == "0x0" ]]; then ok "$host: no under-voltage"
  elif (( t & 0x1 )); then bad "$host: UNDER-VOLTAGE NOW ($t): fix the 5 V supply"
  else bad "$host: under-voltage happened since boot ($t)"; fi
done

# ------------------------------------------------------------------ 4. optionally launch
if [[ ${#LAUNCH[@]} -gt 0 || "${LAUNCH_UI:-0}" -eq 1 ]]; then
  say "Starting: launch_duck.sh ${LAUNCH[*]}"
  exec "$ROOT/scripts/launch_duck.sh" --robot "$URL" "${LAUNCH[@]}"
fi
say "Done. Start the UI with ./scripts/launch_duck.sh (add --brain for Gemma)"
