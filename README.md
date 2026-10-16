# DCS — Duck Control System

Web-based modular control stack for [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini).

Joint IDs and runtime concepts are taken from:

- `/home/venki/repos/embedded/duck mini /Open_Duck_Mini`
- `/home/venki/repos/embedded/duck mini /Open_Duck_Mini_Runtime` (`rustypot_position_hwi.py` motor map)

Servo API target: [python-st3215](https://github.com/Mickael-Roger/python-st3215) (optional; mock mode is default).

## Duck Brain: offline AI desk companion

The `feature/duck-brain` work turns the duck into an expressive desk companion. It's head and eyes only, on a stand, with no walking. **Gemma 3 4B** decides what it says and does, running locally through Ollama.

```text
 Laptop ── hotspot/LAN or Tailscale ──► Pi 4 (DCS :8000, /mcp)          ── USB-C ↔ USB (10.55.0.0/24) ──► Pi Zero 2 W (head)
 brain/: Gemma 3 4B, faster-whisper,    head.control → Feetech IDs 30-33                                eyes_server :8100 → 2× GC9A01
         safety layer, face tracking,   audio.io     → USB mic (VAD) + Piper                            head_camera → head_cam stream
         memory, trace UI :8300         eyes.link    → proxy to the Zero                                boot_status on the eyes at boot
```

| Part | Where |
|---|---|
| Brain harness (Gemma, safety, MCP client, STT, tracking, trace UI) | [`brain/`](brain/README.md) |
| Eyes, head camera, boot-status screens (Pi Zero) | [`devices/head_zero/`](devices/head_zero/README.md) |
| Companion API and MCP tools (head, eyes, speech, e-stop) | `backend/app/routes/companion.py`, `backend/app/nodes/{head_control,eyes_link,audio_io}.py` |
| Duck page (eyes preview, head sliders, STOP, camera, safety events) | `frontend/src/pages/CompanionPage.tsx` → http://…:5173/duck |
| Agent Skill ([agentskills.io](https://agentskills.io/) format) | [`skills/open-duck-control/`](skills/open-duck-control/SKILL.md) |
| Pi 4 ↔ Zero USB network, Zero deploy | `scripts/setup_usb_link.sh`, `scripts/deploy_head_zero.sh` |

**Model:** Gemma 3 4B (`gemma3:4b`, Google DeepMind) under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms). The code in this repository is MIT licensed (see `LICENSE`).

**Built before the hack day vs. for it:**
- **Before:** the DCS core (node runtime, UI pages, servo setup and calibration, video FrameHub, read-only MCP) and the GC9A01 driver and eye art (`emo1.py`).
- **For it:**
  - the eyes service and boot-status screens
  - head control with server-side clamping
  - the companion REST and MCP tools
  - the audio node
  - the Duck page
  - the brain harness (Gemma decisions, safety layer, reflexes, memory, trace UI)
  - the Agent Skill
  - the USB-link networking
  - Picamera2 streaming fixes

**Bring-up order:**
1. `sudo scripts/setup_usb_link.sh pi4|zero` on each Pi, then reboot both.
2. `./scripts/setup_robot.sh` on the Pi 4, and copy `configs/duck_config.example.json` (it has the `companion` section).
   Speaker: the MAX98357A I2S amp (Open Duck Mini wiring: BCLK GPIO18, LRC GPIO19, DIN GPIO21) needs
   `dtoverlay=googlevoicehat-soundcard` in the Pi 4's `/boot/firmware/config.txt`, then a reboot. It only accepts 48 kHz; DCS resamples Piper's output.
3. `./scripts/deploy_head_zero.sh --host bdxmini.local`.
4. On the laptop: `cd brain && uv sync --extra stt && uv run duck-brain`.

## Architecture (nodes)

Every capability is a **Node** (`motors.telemetry`, `video.capture`, `script.v2_rl_walk_mujoco`, …).

- **System → Nodes**: start / stop / restart / **kill** with CPU, logs, config (Tritium-style).
- Kill `video.capture` → `/stream/camera` stops immediately.
- Run `v2_rl_walk_mujoco.py` (serial lock) → motors telemetry yields the bus; stopping walk auto-resumes motors.

```text
Browser (Vite React)
    ↕ REST + WebSocket
FastAPI NodeRuntime
    ├─ NodeRegistry + ResourceLocks
    ├─ MotorsTelemetry (ST3215 or mock)
    ├─ VideoCapture (OpenCV or mock JPEG)
    ├─ SystemMetrics (psutil)
    ├─ FrameHub (video published by scripts)
    └─ ScriptNodes (robot_scripts/**/*.py, spawned subprocesses)
```

## Quick start (localhost)

```bash
cd /home/venki/repos/embedded/DCS
./scripts/setup.sh            # interactive
# or:
./scripts/setup.sh -y --hardware --serial /dev/ttyACM0
```

Then launch both services with one command:

```bash
./scripts/run.sh
```

This starts the FastAPI backend on `:8000`, waits for it to answer `/api/health`, then starts the Vite dev server on `:5173`. Output from both is prefixed `[backend]` / `[frontend]`, and **Ctrl+C stops both**. If either service dies, the other is shut down too.

| Flag | Effect |
|------|--------|
| `--reload` | Run uvicorn with auto-reload for development |
| `--backend-only` | Backend only (same as `./scripts/run_backend.sh`) |
| `--frontend-only` | Frontend only, proxying to an already-running backend |
| `--host` / `--port` | Backend bind address and port |
| `--frontend-port` | Vite dev server port |

The launcher passes the backend location to Vite through `DCS_BACKEND_HOST` / `DCS_BACKEND_PORT`, so `--port` keeps the `/api`, `/ws` and `/stream` proxies pointed at the right place.

Open **http://127.0.0.1:5173/help** for the parameter guide and live config editor.

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

Open http://127.0.0.1:5173 — Vite proxies `/api`, `/ws`, `/stream` to port 8000 (override with `DCS_BACKEND_PORT`).

Remote later: set `VITE_API_BASE` / `VITE_WS_URL` to your host (e.g. `https://…` / `wss://…`).

## Pages

| Page | Status |
|------|--------|
| System / Nodes | Live lifecycle + logs |
| Devices | Motor range bars from duck_config limits |
| Scripts | `robot_scripts/` file tree, templates, edit / run / stop with live logs |
| Camera | MJPEG from `video.capture` or any script-published stream |
| Viz | URDF robot in 3D, MuJoCo-style: joint sliders, collision overlay, live pose |
| Board Pins | Interactive RPi5 / Jetson Orin NX pinout + import/export |
| Control | Key map from config |
| Host | RAM / disk / IPs / processes |
| Terminal | Real local shell over a PTY (off by default) |
| Connections → SSH | Real SSH shell in the browser via xterm.js + paramiko |

## 3D model (Viz page)

The viewer loads `assets/robot.urdf` plus its 45 STL meshes and assembles them with
the URDF kinematic tree, so it behaves like a MuJoCo / RViz viewport: **Z-up** world,
orbit / pan / zoom, a ground grid the duck stands on, visual and collision geometry,
joint frames, and view presets. Joints follow live servo telemetry, or you can switch
to **Manual** and pose all 16 with sliders clamped to the URDF limits.

Assets come from the upstream robot description:

```bash
./scripts/setup.sh --robot-assets <Open_Duck_Mini>/mini_bdx/robots/open_duck_mini_v2
```

> **Do not copy the meshes from `Open_Duck_Mini/print/`.** Those files have the same
> names but are modelled in **millimetres** for 3D printing, while the URDF's joint
> origins are in **metres**. Mixing them makes the viewer draw a 1000x oversized,
> disassembled robot. Scaling the model in the viewer does not fix it — that shrinks
> the joint offsets too, collapsing the parts into each other.

Validate the description at any time:

```bash
python3 scripts/check_robot_assets.py
```

It checks that every referenced mesh exists, that mesh units match the URDF, that the
link tree is fully connected, and that the assembled robot is a plausible ~42 cm duck.

## Scripts

The Scripts page is a file browser over `robot_scripts/`, subfolders included. Drop a whole
project in there (`scp -r`, `git clone`) and it shows up in the tree. Python files can be
edited (Ctrl+S saves), run and stopped; every other file is listed so the structure is visible.

Creating a script asks for a folder, a name, a starter template and the hardware locks it
needs. Templates cover a blank skeleton, a SIGTERM-aware loop, a USB camera publisher, a
motors/serial reader and an IMU reader.

**Running.** Each script runs as its own node: `robot_scripts/tools/scan.py` becomes
`script.tools.scan`, so its stdout/stderr stream into the log panel and the System / Nodes
page. Scripts are spawned with `robot_scripts/` and each embedded package checkout on
`PYTHONPATH`, so `from mini_bdx_runtime.rustypot_position_hwi import HWI` resolves the same
way it does on the robot. Stop sends `SIGTERM` (then `SIGKILL` after ~3 s), so a
`signal.signal(signal.SIGTERM, ...)` handler gets to clean up — and its final output is
captured.

**`manifest.json`** holds the per-script metadata the UI shows: `display_name`,
`description`, `resources` (`serial`, `camera0` — these are real exclusive locks, so starting
a `serial` script pauses `motors.telemetry`) and optional `args` passed on the command line.
Scripts without an entry fall back to their module docstring for the description, and get a
node created on demand the first time you run them.

### Publishing video from a script

`robot_scripts/dcs_sdk.py` is standard library only, so a script that uses it still runs when
you launch it by hand over SSH:

```python
from dcs_sdk import VideoStream

cam = VideoStream("usb_cam", label="USB Camera", fps=15)
while running:
    ok, frame = capture.read()
    cam.publish_frame(frame)      # numpy BGR (encoded with cv2)
    cam.wait_for_next_frame()
```

Frames are POSTed to `/api/video/ingest/{stream_id}` and served back as MJPEG on
`/stream/video/{stream_id}`; the stream appears in the Camera page **Source** dropdown while
frames keep arriving and disappears ~10 s after the script stops. `robot_scripts/camera.py`
is a complete working example:

```bash
python3 camera.py --device 0 --width 640 --height 480 --fps 15
```

`DCS_API_URL`, `DCS_STREAM_ID` and `DCS_NODE_ID` are exported to every script DCS starts;
outside DCS the SDK falls back to `http://127.0.0.1:8000`.

## Terminals

Both terminals are real [xterm.js](https://xtermjs.org/) emulators talking to a backend PTY over a
WebSocket, so escape sequences, scrollback, selection, resize and full-screen programs
(`htop`, `vim`, `less`) all behave as in a native terminal.

**SSH (Connections → SSH)** opens a genuine remote shell through paramiko. Host, port and
username are saved in browser local storage; **passwords and private keys are never stored** —
you are prompted for them each time you connect, and they are held only for the life of that
socket. Pasted hosts are normalised, so `ssh://10.9.9.45/` and `venki@10.9.9.45:22` both work.

**Local (Terminal page)** is a shell on the machine running the backend. It is off unless *both*
of these are set, because it needs no credentials and would otherwise hand a shell to anyone who
can reach the port:

```bash
# 1. configs/duck_config.json
"allow_web_terminal": true
# 2. backend environment
ALLOW_WEB_TERMINAL=1 ./scripts/run.sh
```

`GET /api/terminal/capabilities` reports whether each one is usable and why not.

## Security

Script runner, terminal and SSH are powerful. Keep them on localhost or behind Tailscale.
The local terminal stays off until `allow_web_terminal` + `ALLOW_WEB_TERMINAL=1`; SSH requires
credentials on every connect and stores none.
