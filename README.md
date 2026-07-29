# DCS — Duck Control System

Web-based modular control stack for [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini), implemented at `/home/venki/repos/embedded/DCS`.

Joint IDs and runtime concepts are taken from:

- `/home/venki/repos/embedded/duck mini /Open_Duck_Mini`
- `/home/venki/repos/embedded/duck mini /Open_Duck_Mini_Runtime` (`rustypot_position_hwi.py` motor map)

Servo API target: [python-st3215](https://github.com/Mickael-Roger/python-st3215) (optional; mock mode is default).

## Architecture (nodes)

Every capability is a **Node** (`motors.telemetry`, `video.capture`, `script.rl_walk`, …).

- **System → Nodes**: start / stop / restart / **kill** with CPU, logs, config (Tritium-style).
- Kill `video.capture` → `/stream/camera` stops immediately.
- Run `rl_walk.py` (serial lock) → motors telemetry yields the bus; stopping walk auto-resumes motors.

```text
Browser (Vite React)
    ↕ REST + WebSocket
FastAPI NodeRuntime
    ├─ NodeRegistry + ResourceLocks
    ├─ MotorsTelemetry (ST3215 or mock)
    ├─ VideoCapture (OpenCV or mock JPEG)
    ├─ SystemMetrics (psutil)
    └─ ScriptNodes (robot_scripts/*.py)
```

## Quick start (localhost)

```bash
cd /home/venki/repos/embedded/DCS
./scripts/setup.sh            # interactive
# or:
./scripts/setup.sh -y --hardware --serial /dev/ttyACM0
```

Then start backend + frontend (printed by the script), open **http://127.0.0.1:5173/help** for the parameter guide and live config editor.

### Backend (manual)

```bash
cd /home/venki/repos/embedded/DCS/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional on robot: pip install st3215 opencv-python-headless
cp ../configs/duck_config.example.json ../configs/duck_config.json
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Set `"mock_hardware": false` in `configs/duck_config.json` when `/dev/ttyACM0` and ST3215 are available. Or use the **Help / Setup** page in the UI.

### Frontend

```bash
cd /home/venki/repos/embedded/DCS/frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — Vite proxies `/api`, `/ws`, `/stream` to port 8000.

Remote later: set `VITE_API_BASE` / `VITE_WS_URL` to your host (e.g. `https://…` / `wss://…`).

## Pages

| Page | Status |
|------|--------|
| System / Nodes | Live lifecycle + logs |
| Devices | Motor range bars from duck_config limits |
| Scripts | Monaco edit / save / run / stop |
| Camera | MJPEG bound to `video.capture` node |
| Viz | Tree + live joint overlay (URDF mesh later) |
| Board Pins | Interactive RPi5 / Jetson Orin NX pinout + import/export |
| Control | Key map from config |
| Host | RAM / disk / IPs / processes |
| Terminal / SSH | UI stubs; SSH profiles in localStorage |

## Wire real Open Duck Mini scripts

Replace placeholders in `robot_scripts/` with wrappers that call Runtime entrypoints, e.g. `v2_rl_walk_mujoco.py`, and keep `manifest.json` `resources: ["serial"]` for walk.

URDF reference: `Open_Duck_Mini/mini_bdx/robots/open_duck_mini_v2/robot.urdf`.

## Security

Script runner / terminal / SSH proxy are powerful. Keep them localhost or behind Tailscale; terminal stays off until `allow_web_terminal` + env flag.
