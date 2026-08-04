# Settings, Setup, MCP & Deployment Implementation

Covers five work streams: Help page cleanup, Settings page, Setup page (calibration + servo IDs), MCP server with dev mode, and split deployment scripts.

> [!NOTE]
> All user confirmations incorporated: servo one-at-a-time workflow ✓, calibration with safety controls ✓, MCP dev mode toggle ✓

---

## Proposed Changes

### Component 1: Help Page Cleanup

#### [NEW] [HelpPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpPage.tsx)

Clean, read-only informational page. Three sections displayed inline (no tabs that fail to load):

1. **Getting Started** — setup steps from `/api/help` (CLI commands, quick-start)
2. **Parameter Reference** — grouped parameter docs as read-only cards (key, type, default, summary, details). No edit controls.
3. **UI Pages Guide** — table of all pages with links and descriptions

Header shows links to Settings and Setup pages for users who want to make changes.

#### [DELETE] [HelpSetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpSetupPage.tsx)

---

### Component 2: Settings Page

#### [NEW] [SettingsPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/SettingsPage.tsx)

All config editing consolidated here. Left sidebar groups, right panel with edit controls:

| Group | Fields |
|---|---|
| **Robot** | `robot_id`, `robot_name` |
| **Servos** | `serial_port`, `baudrate`, `poll_hz`, `mock_hardware`, `serial_policy` |
| **Camera** | `camera_device`, `camera_width`, `camera_height`, rotation, fps, flip |
| **Joints** | Editable table of joint IDs + min/max limits |
| **Joint Offsets** | Table of current offsets + link to Setup calibration wizard |
| **UI Scales** | Telemetry scale ranges |
| **Nodes** | Toggle auto-start for each node |
| **Control** | Keymap editor |
| **Security** | `allow_script_runner`, `allow_web_terminal`, **`mcp_dev_mode`** (new) |
| **Raw JSON** | Full textarea JSON editor for advanced users |

Header: Save / Reset / Revert buttons with success/error notifications.

The **Security** group includes the new `mcp_dev_mode` toggle with a clear warning:

> ⚠️ MCP Dev Mode allows AI models to execute dangerous operations (config changes, script execution, servo control). Enable at your own risk.

---

### Component 3: Setup Page — Calibration & Servo ID

#### Backend

##### [NEW] [setup.py](file:///home/venki/repos/embedded/DCS/backend/app/routes/setup.py)

New FastAPI router:

```
# Servo ID Management
POST /api/setup/servo/scan                         → Scan bus for servo IDs
POST /api/setup/servo/set-id                       → Change servo ID {current_id, new_id}
GET  /api/setup/servo/status                       → All joints: expected ID + online status

# Joint Calibration
POST /api/setup/calibration/start                  → Pause motors.telemetry, init serial
POST /api/setup/calibration/stop                   → Release serial, resume motors.telemetry
GET  /api/setup/calibration/status                 → Current session state + offsets so far
POST /api/setup/calibration/move-to-zero           → Move all joints to zero
POST /api/setup/calibration/joint/disable-torque    → {joint_name} — release one joint
POST /api/setup/calibration/joint/enable-torque     → {joint_name} — re-engage torque
POST /api/setup/calibration/joint/read-position     → {joint_name} → {position_rad}
POST /api/setup/calibration/joint/set-offset        → {joint_name, offset}
POST /api/setup/calibration/save                    → Write joints_offsets to duck_config.json
POST /api/setup/calibration/emergency-stop          → Disable ALL torque immediately
```

##### [NEW] [servo_setup.py](file:///home/venki/repos/embedded/DCS/backend/app/services/servo_setup.py)

Service class wrapping serial communication:

- Uses `st3215` library (consistent with motors telemetry node)
- Mock mode: returns simulated data for UI dev/testing
- **Calibration flow** (mirrors `find_soft_offsets.py`):
  1. `init_session(port, baudrate)` → open serial, move all to zero
  2. `disable_joint_torque(joint_id)` → user physically moves it
  3. `read_position(joint_id)` → get raw position in radians
  4. Offset = new_position - zero_position (computed in route handler)
  5. `enable_joint_torque(joint_id)` → apply offset, move to zero
  6. `save_offsets(offsets_dict)` → write to duck_config.json
  7. `emergency_stop()` → disable torque on all servo IDs
- **Servo ID flow** (mirrors `configure_motor.py`):
  1. `scan_bus(port)` → try IDs 1–253, return found list
  2. `set_servo_id(port, current_id, new_id)` → unlock, set mode/PID/acceleration defaults, change ID
  3. `get_servo_status(port, expected_ids)` → which configured IDs respond

#### Frontend

##### [NEW] [SetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/SetupPage.tsx)

Two-tab layout:

**Tab 1 — Servo ID Configuration:**
- Status grid: 14 joints, each showing name, expected ID, ✓/✗ status
- "Scan Bus" button → calls `/api/setup/servo/scan`
- If all 14 found → green banner "All Servos Configured ✓"
- If any missing → instruction panel:
  1. "Connect ONE new servo to the bus"
  2. "Click Scan" → finds new servo (usually ID 1)
  3. Select target joint from dropdown
  4. "Assign ID" button → calls `/api/setup/servo/set-id`
  5. Verify step → re-scan and confirm

**Tab 2 — Joint Offset Calibration:**
- Safety warning banner: "⚠️ Robot will move. Place on stand."
- **Start Session** button → pauses motors.telemetry
- Joint list (14 items) with status chips: `pending` | `in progress` | `calibrated ✓` | `skipped`
- Per-joint calibration flow (expandable card):
  1. **Begin** → move all to zero, read current position
  2. **Release** → disable torque, show "Move joint to desired zero"
  3. **Record** → read new position, display offset
  4. **Test** → re-enable torque, move to zero with offset
  5. **Accept** / **Retry** / **Skip** buttons
- Running summary table of all offsets
- **Save Config** button → writes to `duck_config.json`
- **Emergency Stop** button — always visible, red, prominent

---

### Component 4: MCP Server

#### [MODIFY] [requirements.txt](file:///home/venki/repos/embedded/DCS/backend/requirements.txt)

Add: `fastapi-mcp>=0.4.0`

#### [NEW] [mcp_server.py](file:///home/venki/repos/embedded/DCS/backend/app/mcp_server.py)

```python
from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

def setup_mcp(app: FastAPI) -> FastApiMCP:
    mcp = FastApiMCP(
        app,
        name="DCS Robot Control",
        description="Duck Control System — robot management API for AI agents",
        base_url="http://localhost:8000",
    )
    mcp.mount()  # Serves at /mcp
    return mcp
```

**Two modes controlled by `mcp_dev_mode` in duck_config.json:**

| Mode | Exposed operations |
|---|---|
| **Default (read-only)** | `GET /api/health`, `GET /api/config`, `GET /api/motors`, `GET /api/system`, `GET /api/pinout`, `GET /api/scripts`, `GET /api/robot/model`, `GET /api/help` |
| **Dev mode** | All of the above PLUS: `PUT /api/config`, `POST /api/scripts/run/*`, `POST /api/scripts/stop/*`, all `/api/setup/*` endpoints, `POST /api/bluetooth/*` |

Implementation: `FastApiMCP` has `include_operations` / `exclude_operations` filters based on route `operation_id`. The MCP setup reads `mcp_dev_mode` from config and conditionally includes dangerous operations.

#### [MODIFY] [schemas.py](file:///home/venki/repos/embedded/DCS/backend/app/schemas.py)

Add to `DuckConfig`:
```python
mcp_dev_mode: bool = False
```

#### [MODIFY] [main.py](file:///home/venki/repos/embedded/DCS/backend/app/main.py)

- Import and register `setup.py` router
- Import and call `setup_mcp(app)` in `create_app()`
- MCP endpoint available at `/mcp` (SSE transport)

#### [MODIFY] [help_schema.py](file:///home/venki/repos/embedded/DCS/backend/app/help_schema.py)

- Update `PAGE_GUIDE` to include Settings, Setup pages
- Add `mcp_dev_mode` to `PARAMETER_HELP`
- Update Help page blurb

---

### Component 5: Deployment Scripts

The goal: users can deploy **backend only** to the robot (lightweight, headless) and run the **frontend separately** on their PC, pointing at the robot's IP.

#### [NEW] [setup_robot.sh](file:///home/venki/repos/embedded/DCS/scripts/setup_robot.sh)

Backend-only setup for the robot. Essentially `setup.sh` with `--no-frontend --hardware`:

```bash
#!/usr/bin/env bash
# Deploy DCS backend to the robot (no frontend, real hardware)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/setup.sh" --no-frontend --hardware "$@"
```

Also prints helpful instructions at the end:
```
=== Robot backend deployed ===
Start:  ./scripts/run.sh --backend-only
The API will be at http://<robot-ip>:8000

On your PC, run:
  ./scripts/run_frontend.sh --backend-url http://<robot-ip>:8000
```

#### [NEW] [setup_frontend.sh](file:///home/venki/repos/embedded/DCS/scripts/setup_frontend.sh)

Frontend-only setup for the PC. Installs npm deps, skips Python/hardware entirely:

```bash
#!/usr/bin/env bash
# Set up DCS frontend on your PC (no backend, no Python)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

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
```

#### [NEW] [run_frontend.sh](file:///home/venki/repos/embedded/DCS/scripts/run_frontend.sh)

Launches frontend pointing at a remote backend:

```bash
#!/usr/bin/env bash
# Run DCS frontend, connecting to a remote backend
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

BACKEND_URL=""
FRONTEND_HOST="0.0.0.0"
FRONTEND_PORT="5173"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url) BACKEND_URL="$2"; shift 2 ;;
    --host) FRONTEND_HOST="$2"; shift 2 ;;
    --port) FRONTEND_PORT="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

if [[ -z "$BACKEND_URL" ]]; then
  echo "Usage: $0 --backend-url http://<robot-ip>:8000" >&2
  exit 1
fi

# Parse host:port from URL for Vite proxy
BACKEND_HOST=$(echo "$BACKEND_URL" | sed 's|https\?://||' | cut -d: -f1)
BACKEND_PORT=$(echo "$BACKEND_URL" | sed 's|https\?://||' | cut -d: -f2 | cut -d/ -f1)

echo "Frontend → Backend at $BACKEND_URL"
cd "$ROOT/frontend"
export DCS_BACKEND_HOST="$BACKEND_HOST"
export DCS_BACKEND_PORT="$BACKEND_PORT"
exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
```

This works because `vite.config.ts` already reads `DCS_BACKEND_HOST` and `DCS_BACKEND_PORT` env vars to configure the proxy target. No code changes needed in Vite config.

#### [MODIFY] [setup.sh](file:///home/venki/repos/embedded/DCS/scripts/setup.sh)

Update the completion message to mention the new split deployment scripts.

#### [MODIFY] [run.sh](file:///home/venki/repos/embedded/DCS/scripts/run.sh)

Update the help output to mention `run_frontend.sh` for remote backend connections.

---

## File Summary

| Action | File | Component |
|---|---|---|
| NEW | `frontend/src/pages/HelpPage.tsx` | Help cleanup |
| DELETE | `frontend/src/pages/HelpSetupPage.tsx` | Help cleanup |
| NEW | `frontend/src/pages/SettingsPage.tsx` | Settings |
| NEW | `frontend/src/pages/SetupPage.tsx` | Setup/Calibration |
| MODIFY | `frontend/src/App.tsx` | Routing + nav |
| MODIFY | `frontend/src/styles.css` | New component styles |
| NEW | `backend/app/routes/setup.py` | Setup API endpoints |
| NEW | `backend/app/services/servo_setup.py` | Serial hardware service |
| NEW | `backend/app/mcp_server.py` | MCP integration |
| MODIFY | `backend/app/main.py` | Register setup router + MCP |
| MODIFY | `backend/app/schemas.py` | Add `mcp_dev_mode` field |
| MODIFY | `backend/app/help_schema.py` | Update page guide + params |
| MODIFY | `backend/requirements.txt` | Add `fastapi-mcp` |
| NEW | `scripts/setup_robot.sh` | Robot-only deploy |
| NEW | `scripts/setup_frontend.sh` | PC-only frontend setup |
| NEW | `scripts/run_frontend.sh` | Remote backend frontend launcher |
| MODIFY | `scripts/setup.sh` | Updated completion message |
| MODIFY | `scripts/run.sh` | Updated help text |

---

## Verification Plan

### Automated Tests
```bash
# Backend builds and starts
cd backend && .venv/bin/python -c "from app.main import app; print('OK')"

# Frontend builds without TS errors
cd frontend && npm run build

# API endpoints respond in mock mode
curl http://localhost:8000/api/setup/servo/status
curl -X POST http://localhost:8000/api/setup/servo/scan
curl http://localhost:8000/api/setup/calibration/status
curl http://localhost:8000/mcp  # MCP server

# Deployment scripts are executable
bash scripts/setup_robot.sh --help
bash scripts/setup_frontend.sh --help
bash scripts/run_frontend.sh --help
```

### Browser Testing
- `/help` — verify read-only, no broken tabs
- `/settings` — edit `robot_name`, save, verify header updates; toggle `mcp_dev_mode`
- `/setup` — walk through servo scan and calibration wizard in mock mode
- `/mcp` — verify MCP server responds

### Manual (Real Hardware)
- Connect servos, test scan + ID assignment
- Run full calibration wizard, save offsets, verify `duck_config.json`
- Split deployment: backend on robot, frontend on PC via `run_frontend.sh`
