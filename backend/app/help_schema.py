"""Human-readable parameter docs for the Help / Setup UI."""

from __future__ import annotations

from typing import Any

# Flat parameter metadata for duck_config.json top-level + common nested keys.
PARAMETER_HELP: list[dict[str, Any]] = [
    {
        "key": "robot_id",
        "group": "Robot",
        "type": "string",
        "default": "duck-mini-001",
        "summary": "Short unique id shown in the header and API health.",
        "details": "Use something stable per physical duck (e.g. duck-lab-02). No spaces preferred.",
    },
    {
        "key": "robot_name",
        "group": "Robot",
        "type": "string",
        "default": "Open Duck Mini",
        "summary": "Friendly display name in the UI header.",
        "details": "Shown next to robot_id, e.g. Open Duck Mini.",
    },
    {
        "key": "serial_port",
        "group": "Servos",
        "type": "string",
        "default": "/dev/ttyACM0",
        "summary": "USB serial device for the Feetech / ST3215 bus.",
        "details": "On Pi/Jetson usually /dev/ttyACM0 or /dev/ttyUSB0. Only one process may open this port (motors telemetry or rl_walk).",
    },
    {
        "key": "baudrate",
        "group": "Servos",
        "type": "int",
        "default": 1000000,
        "summary": "Bus baud rate for ST3215 servos.",
        "details": "Open Duck Mini Runtime uses 1_000_000. Must match servo EEPROM baud setting.",
    },
    {
        "key": "poll_hz",
        "group": "Servos",
        "type": "float",
        "default": 15,
        "summary": "How often motors.telemetry reads all joints (Hz).",
        "details": "Higher = smoother Devices UI, more serial traffic. Typical 10–20. Lower if sharing bus timing with scripts.",
    },
    {
        "key": "mock_hardware",
        "group": "Servos",
        "type": "bool",
        "default": True,
        "summary": "If true, generate fake motor (and mock camera) data without hardware.",
        "details": "Keep true for laptop/dev. Set false on the robot after installing st3215 and connecting the bus.",
    },
    {
        "key": "camera_device",
        "group": "Camera",
        "type": "string / int",
        "default": 0,
        "summary": "Camera device index (e.g. 0) or path (e.g. /dev/video0).",
        "details": "OpenCV video capture device. Index 0 or 1 for USB/CSI camera.",
    },
    {
        "key": "camera_width",
        "group": "Camera",
        "type": "int",
        "default": 640,
        "summary": "Video frame width in pixels.",
        "details": "Stream frame resolution width (e.g. 640, 1280).",
    },
    {
        "key": "camera_height",
        "group": "Camera",
        "type": "int",
        "default": 480,
        "summary": "Video frame height in pixels.",
        "details": "Stream frame resolution height (e.g. 480, 720).",
    },
    {
        "key": "serial_policy",
        "group": "Servos",
        "type": "enum",
        "default": "prefer_script",
        "options": ["prefer_script", "prefer_telemetry"],
        "summary": "Who wins when both walk script and motors telemetry need serial.",
        "details": "prefer_script: starting rl_walk pauses motors.telemetry. prefer_telemetry: refuse script start while telemetry holds the lock.",
    },
    {
        "key": "joints",
        "group": "Joints",
        "type": "object",
        "summary": "Per-joint servo id and end limits (min/max) in radians.",
        "details": "IDs match Open Duck Mini Runtime HWI. min/max scale Devices range bars and will clamp future write controls. Edit carefully — wrong limits mis-scale the UI.",
    },
    {
        "key": "joints_offsets",
        "group": "Joints",
        "type": "object",
        "summary": "Calibration offsets (rad) added when commanding positions.",
        "details": "From duck_config in Open Duck Mini Runtime. Telemetry-only phase stores them for later write/walk integration.",
    },
    {
        "key": "telemetry_scales",
        "group": "UI scales",
        "type": "object",
        "summary": "Min/max for temperature, voltage, current, load, speed bars.",
        "details": "Does not change hardware — only Devices page normalization. Match STS3215 datasheet ranges where possible.",
    },
    {
        "key": "nodes",
        "group": "Nodes",
        "type": "object",
        "summary": "Which nodes auto-start when the backend boots.",
        "details": "Keys are node ids (motors.telemetry, video.capture, system.metrics). Scripts are never auto-started from this map.",
    },
    {
        "key": "control.keymap",
        "group": "Control",
        "type": "object",
        "summary": "Xbox / gamepad action → axis or button mapping.",
        "details": "Shown on the Control page. Pair the controller with bluetoothctl on the host; Joy node reads these ids later.",
    },
    {
        "key": "allow_script_runner",
        "group": "Security",
        "type": "bool",
        "default": True,
        "summary": "Allow Scripts page edits, creation and Run (arbitrary Python as backend user).",
        "details": (
            "Disable on untrusted networks: it also blocks creating, renaming and deleting files "
            "under robot_scripts/. Running scripts can take serial/camera locks."
        ),
    },
    {
        "key": "allow_web_terminal",
        "group": "Security",
        "type": "bool",
        "default": False,
        "summary": "Enable browser PTY terminal (off by default).",
        "details": "Also requires ALLOW_WEB_TERMINAL=1 env when the terminal backend is enabled. Treat as root-equivalent access.",
    },
]

PAGE_GUIDE: list[dict[str, str]] = [
    {
        "page": "System / Nodes",
        "path": "/system/nodes",
        "blurb": "List every node. Start/Stop/Kill. Kill video.capture stops the camera stream.",
    },
    {
        "page": "Devices",
        "path": "/devices",
        "blurb": "Motor tree and range bars. Needs motors.telemetry running. Limits come from joints + telemetry_scales.",
    },
    {
        "page": "Scripts",
        "path": "/scripts",
        "blurb": (
            "Browse robot_scripts/ as a folder tree, create scripts from templates, rename, "
            "delete, edit (Ctrl+S saves) and run them with live stdout/stderr. Each script runs "
            "as its own node, taking the serial/camera locks listed in robot_scripts/manifest.json. "
            "Import dcs_sdk in a script to publish video to the Camera page."
        ),
    },
    {
        "page": "Camera",
        "path": "/camera",
        "blurb": (
            "MJPEG viewer with a Source dropdown: the built-in video.capture node or any script "
            "publishing frames through dcs_sdk.VideoStream. Rotation/flip apply in the browser; "
            "resolution and FPS configure video.capture."
        ),
    },
    {
        "page": "Viz (3D model)",
        "path": "/viz",
        "blurb": (
            "URDF robot in a MuJoCo-style Z-up viewport: orbit/pan/zoom, visual and collision "
            "geometry, joint frames, view presets. Joints follow live telemetry, or switch to "
            "Manual to pose all 16 within their URDF limits. Needs assets/robot.urdf + meshes; "
            "verify with: python3 scripts/check_robot_assets.py"
        ),
    },
    {
        "page": "Board Pins",
        "path": "/pins",
        "blurb": "Pick RPi5 / Jetson Orin NX pinout, attach LEDs/sensors, export/import schema.",
    },
    {
        "page": "Connections",
        "path": "/connections",
        "blurb": (
            "Bluetooth scan/pair (Xbox), Network interfaces/Wi‑Fi/DNS/routes, and a real SSH "
            "terminal. Host/port/user are saved locally; the password or key is asked for on "
            "every connect and never stored."
        ),
    },
    {
        "page": "Terminal",
        "path": "/terminal",
        "blurb": (
            "Shell on the backend machine. Needs allow_web_terminal=true plus ALLOW_WEB_TERMINAL=1 "
            "because it requires no credentials. For remote hosts use Connections → SSH."
        ),
    },
    {
        "page": "Help / Setup",
        "path": "/help",
        "blurb": "This page — explain parameters and save duck_config.json.",
    },
]

SETUP_STEPS: list[dict[str, str]] = [
    {
        "title": "1. Run the setup script",
        "body": "./scripts/setup.sh   # or: ./scripts/setup.sh -y --hardware --serial /dev/ttyACM0",
    },
    {
        "title": "2. Launch backend + frontend",
        "body": "./scripts/run.sh  →  http://127.0.0.1:5173 (Ctrl+C stops both). Add --reload for auto-reload, or --backend-only / --frontend-only to run one side.",
    },
    {
        "title": "3. Configure in UI",
        "body": "Open Help / Setup, adjust robot id, serial, mock mode, poll rate, save. Restart motors node if you flipped mock_hardware.",
    },
    {
        "title": "4. On the robot",
        "body": "mock_hardware=false, install st3215, udev latency for USB serial (see Open Duck Mini Runtime README).",
    },
]
