# Settings, Setup & MCP Server Implementation

This plan addresses four major work streams: cleaning up the Help page, creating a new Settings page, building a robot Setup page with calibration & servo ID tools, and adding an MCP server for AI model integration.

## User Review Required

> [!IMPORTANT]
> **Servo ID Assignment** requires connecting servos **one at a time** to the bus (new servos default to ID 1). The UI flow assumes this workflow — plug one servo, scan, assign its target ID, unplug, repeat. Please confirm this matches your physical setup workflow.

> [!IMPORTANT]
> **Joint Calibration** drives real hardware — it disables torque on individual joints so you can physically move them, then records the offset. The UI will have explicit safety warnings and an emergency stop button. The motors.telemetry node will be **paused** during calibration to avoid serial bus conflicts.

> [!WARNING]
> **MCP Server** exposes DCS APIs to AI models. By default, dangerous operations (E-stop, config save, script execution) will require explicit confirmation or be gated behind `allow_script_runner`. Read-only operations (telemetry, config read, joint status) are exposed freely.

## Open Questions

> [!IMPORTANT]
> 1. For the MCP server, do you want **SSE transport** (http-based, works with remote models) or **stdio transport** (local only, for Claude Desktop)? I'll implement SSE by default since you mentioned both local and online models.
> 2. Should the Setup page be accessible even in mock mode (with mock data for calibration preview), or only when `mock_hardware=false`?
> 3. The reference repo uses `pypot.feetech.FeetechSTS3215IO` for servo ID configuration and `rustypot` for the HWI calibration. Your repo already has both scripts in `robot_scripts/`. Should the backend use `st3215` (already in the motors telemetry node) or `pypot` for the ID assignment? I'll default to `st3215` since it's already a dependency pattern.

---

## Proposed Changes

### Component 1: Help Page Cleanup

The current [HelpSetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpSetupPage.tsx) mixes informational content with settings editing. The buggy "Setup", "Pages", and "JSON" tabs will be removed. The page becomes a pure read-only documentation/reference page.

#### [MODIFY] [HelpSetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpSetupPage.tsx)

- **Rename** to `HelpPage.tsx` (new file, delete old)
- Remove all config editing state (`draft`, `save`, `resetDraft`, `setField`)
- Remove "Setup", "Pages", "JSON" tabs from the sidebar
- Remove Save/Reset buttons from the header
- Keep the parameter groups as **read-only documentation** — show `key`, `type`, `default`, `summary`, `details` without edit controls
- Add the **Pages** information inline as a permanent section (not a tab that "loads nothing")
- Add links to the new Settings and Setup pages
- Clean, info-only layout with sections: "Parameter Reference", "UI Pages Guide", "Getting Started"

#### [NEW] [HelpPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpPage.tsx)

Clean informational page with:
- **Getting Started** section (the setup steps from the API, displayed inline)
- **Parameter Reference** — grouped parameter docs (read-only cards)
- **UI Pages Guide** — table of pages with links and descriptions
- No edit controls whatsoever

#### [DELETE] [HelpSetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/HelpSetupPage.tsx)

---

### Component 2: New Settings Page

All configuration editing moves here. This is the "control panel" for duck_config.json.

#### [NEW] [SettingsPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/SettingsPage.tsx)

- Left sidebar with setting groups: `Robot`, `Servos`, `Camera`, `Joints`, `UI Scales`, `Nodes`, `Control`, `Security`, `Raw JSON`
- Each group shows editable fields (the same edit controls from the old HelpSetupPage)
- **Robot**: `robot_id`, `robot_name`
- **Servos**: `serial_port`, `baudrate`, `poll_hz`, `mock_hardware`, `serial_policy`
- **Camera**: `camera_device`, `camera_width`, `camera_height`, etc.
- **Joints**: editable table of joint IDs, min/max limits (with inline editing)
- **Joint Offsets**: editable table showing current offsets (with link to Setup page for calibration wizard)
- **UI Scales**: telemetry scale ranges
- **Nodes**: toggle auto-start nodes
- **Control**: keymap editor
- **Security**: `allow_script_runner`, `allow_web_terminal`
- **Raw JSON**: textarea editor for advanced users (migrated from old "JSON" tab)
- Save/Reset/Revert buttons in header
- Success/error notifications

#### [MODIFY] [App.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/App.tsx)

- Add `SettingsPage` and `SetupPage` imports
- Add nav items: `{ to: "/settings", label: "Settings", icon: "⚙" }` and `{ to: "/setup", label: "Setup", icon: "🔧" }`
- Add routes: `/settings` → `SettingsPage`, `/setup` → `SetupPage`
- Update `/help` route to use new `HelpPage`
- Remove `HelpSetupPage` import

#### [MODIFY] [help_schema.py](file:///home/venki/repos/embedded/DCS/backend/app/help_schema.py)

- Update `PAGE_GUIDE` to include Settings and Setup pages
- Update the Help page blurb to reflect its new read-only nature

---

### Component 3: Setup Page — Robot Calibration & Servo ID

This is the most complex component. It has two main sections: **Servo ID Configuration** and **Joint Offset Calibration**.

#### Backend API Endpoints

##### [NEW] [setup.py](file:///home/venki/repos/embedded/DCS/backend/app/routes/setup.py)

New router with calibration and servo ID endpoints:

```python
# Servo ID Management
POST /api/setup/servo/scan          # Scan bus for servos (returns list of found IDs)
POST /api/setup/servo/set-id        # Change a servo's ID {current_id, new_id, port}
GET  /api/setup/servo/status        # Check if all expected joints have responding servos

# Joint Offset Calibration
POST /api/setup/calibration/start   # Begin calibration session (pauses motors.telemetry)
POST /api/setup/calibration/stop    # End calibration session (resumes motors.telemetry)
GET  /api/setup/calibration/status  # Current calibration state
POST /api/setup/calibration/joint/disable-torque  # Disable torque on specific joint {joint_name}
POST /api/setup/calibration/joint/enable-torque   # Re-enable torque {joint_name}
POST /api/setup/calibration/joint/read-position   # Read current position {joint_name}
POST /api/setup/calibration/joint/goto-zero       # Move joint to zero position {joint_name}
POST /api/setup/calibration/joint/set-offset      # Record offset for a joint {joint_name, offset}
POST /api/setup/calibration/save    # Write all offsets to duck_config.json
POST /api/setup/calibration/emergency-stop  # Disable all torque immediately
```

##### [NEW] [servo_setup.py](file:///home/venki/repos/embedded/DCS/backend/app/services/servo_setup.py)

Service layer that wraps the serial communication for calibration:

- `ServoSetupService` class manages serial port access
- Uses `st3215` library (same as motors telemetry) for real hardware
- Mock mode returns simulated responses for UI testing
- Implements the `find_soft_offsets.py` logic as discrete API-callable steps:
  1. Move all joints to zero → `goto_zero_all()`
  2. For a given joint: read current position → `read_position(joint_id)`
  3. Disable torque on joint → `disable_torque(joint_id)`
  4. Read new position after manual adjustment → `read_position(joint_id)`
  5. Calculate offset = new_pos - current_pos
  6. Apply offset and move to zero with offset → `goto_zero_with_offset(joint_id, offset)`
  7. Re-enable torque → `enable_torque(joint_id)`
- Implements servo ID scan and change (from `configure_motor.py` logic):
  1. Scan IDs 1-253 → `scan_bus(port)`
  2. Change ID → `change_servo_id(port, current_id, new_id)`
  3. Configure servo defaults (PID, mode, acceleration) → `configure_servo(port, servo_id)`

#### Frontend

##### [NEW] [SetupPage.tsx](file:///home/venki/repos/embedded/DCS/frontend/src/pages/SetupPage.tsx)

Two-section page with tab navigation:

**Tab 1: Servo ID Configuration**
- Status panel showing all 14 joints with their expected IDs and online/offline status
- "Scan Bus" button that hits `/api/setup/servo/scan`
- Per-servo row: joint name, expected ID, current status (✓ found / ✗ missing)
- For unconfigured servos: "Connect one servo at a time" instruction panel
- Workflow:
  1. User connects a new servo (default ID 1)
  2. Clicks "Scan" → finds servo at ID 1
  3. Selects which joint this servo is for (dropdown)
  4. Clicks "Assign ID" → calls `/api/setup/servo/set-id`
  5. Status updates to show the servo is now configured
- If all servos already configured → show green "All Servos Configured ✓" banner

**Tab 2: Joint Calibration (Offset Wizard)**
- **Step-by-step wizard UI** inspired by `find_soft_offsets.py`:
  1. Safety warning banner: "Robot will move to zero position. Ensure robot is on a stand."
  2. "Start Calibration" button → pauses motors.telemetry, initializes serial
  3. Joint list with progress indicators (not started / in progress / calibrated / skipped)
  4. Per-joint calibration card:
     - Joint name and ID displayed prominently
     - "Begin" button → moves robot to zero, records current position
     - "Release Motor" button → disables torque on this joint
     - Instruction: "Physically move joint to desired zero position"
     - "Record Position" button → reads new position, calculates offset
     - Displays calculated offset value
     - "Test Zero" button → re-enables torque, moves to zero with offset applied
     - "Accept" / "Retry" buttons
  5. Running offset summary table (updates as each joint is calibrated)
  6. "Save Config" button → writes all `joints_offsets` to `duck_config.json`
  7. "Emergency Stop" button (always visible, red, large) → disables all torque

#### Styles

##### [MODIFY] [styles.css](file:///home/venki/repos/embedded/DCS/frontend/src/styles.css)

Add styles for:
- Setup wizard steps and progress indicators
- Servo status badges (online/offline/unconfigured)
- Calibration card layout
- Safety warning banners
- Emergency stop button styling

---

### Component 4: MCP Server Integration

Using `fastapi-mcp` to expose existing DCS APIs as MCP tools.

#### [MODIFY] [requirements.txt](file:///home/venki/repos/embedded/DCS/backend/requirements.txt)

Add:
```
fastapi-mcp>=0.4.0
```

#### [NEW] [mcp_server.py](file:///home/venki/repos/embedded/DCS/backend/app/mcp_server.py)

MCP server configuration:

```python
from fastapi_mcp import FastApiMCP

def setup_mcp(app: FastAPI) -> FastApiMCP:
    mcp = FastApiMCP(
        app,
        name="DCS Robot Control",
        description="Duck Control System — robot management API",
        base_url="http://localhost:8000",
    )
    mcp.mount()
    return mcp
```

This auto-exposes all existing API routes as MCP tools:

**Read-only tools (always available):**
- `health` → GET /api/health
- `get_config` → GET /api/config
- `list_motors` → GET /api/motors
- `system_snapshot` → GET /api/system
- `get_pinout` → GET /api/pinout
- `list_scripts` → GET /api/scripts
- `get_robot_model` → GET /api/robot/model

**Action tools (gated by config/confirmation):**
- `put_config` → PUT /api/config (config changes)
- `run_script` → POST /api/scripts/run/{rel} (requires `allow_script_runner`)
- `stop_script` → POST /api/scripts/stop/{rel}
- `calibration/*` → Setup endpoints
- `servo/*` → Setup endpoints

#### [MODIFY] [main.py](file:///home/venki/repos/embedded/DCS/backend/app/main.py)

- Import and call `setup_mcp(app)` in `create_app()`
- MCP endpoint available at `/mcp` (SSE transport)

---

## Verification Plan

### Automated Tests

1. **Backend API tests:**
   ```bash
   # Test setup endpoints respond correctly in mock mode
   curl http://localhost:8000/api/setup/servo/scan
   curl -X POST http://localhost:8000/api/setup/calibration/start
   curl http://localhost:8000/api/setup/calibration/status
   
   # Test MCP endpoint is available
   curl http://localhost:8000/mcp
   ```

2. **Frontend build:**
   ```bash
   cd frontend && npm run build  # Verify no TypeScript/build errors
   ```

3. **Browser testing:**
   - Navigate to `/help` — verify no edit controls, only documentation
   - Navigate to `/settings` — verify all config editing works, save/reset
   - Navigate to `/setup` — verify servo scan UI and calibration wizard render
   - Navigate to `/mcp` — verify MCP server responds

### Manual Verification

1. **Help page**: Confirm "Setup", "Pages", "JSON" tabs are gone; page is purely informational
2. **Settings page**: Edit `robot_name`, save, verify header updates
3. **Setup page** (mock mode): Walk through calibration wizard, verify mock offsets are generated and can be saved
4. **Setup page** (real hardware): Connect servos, test scan, assign IDs, run calibration
5. **MCP server**: Connect an AI client (e.g., Claude Desktop or Cursor) to `http://localhost:8000/mcp` and verify it can read robot status
