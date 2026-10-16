# Head Pi Zero 2 W: eyes, ears, lamp, head camera, boot status

These services run on the Raspberry Pi Zero 2 W inside the duck's head (hostname `bdxmini`). It connects to
the Pi 4 by USB (Pi 4 USB-C ↔ Zero USB data port), which carries power and a private Ethernet link:
Pi 4 `10.55.0.1`, Zero `10.55.0.2`. See `scripts/setup_usb_link.sh`.

| File | What it does |
|---|---|
| `eyes_server.py` | HTTP API on `:8100`: expressions, gaze, blink, preview PNG, calibration. `--mock` runs without displays |
| `eye_engine.py` | Animation thread: eases toward the commanded expression and gaze, idle saccades, blinks, ~30 fps cap |
| `eye_renderer.py` | The eye drawing from `emo1.py` (eyelids, pupils, highlights) and dirty-rectangle updates |
| `expressions.json` | Expression presets: 6 from `emo1.py` plus thinking, listening, curious, suspicious, grumpy |
| `gc9a01_driver.py` | GC9A01 SPI driver (unchanged) |
| `eye_config.json` | Per-eye rotation and offset (left −91°, right 110°); editable through `PUT /calibration` |
| `head_camera.py` | CSI camera → hardware MJPEG encoder → DCS stream `head_cam` (newest frame only) |
| `boot_status.py` | Status screens on both eyes until the robot is ready, then hands over to the eyes |
| `systemd/` | `duck-boot-status` (enabled) → `duck-eyes` → `duck-headcam` |

## Wiring (BCM)

| | Left eye | Right eye |
|---|---|---|
| SPI | SPI0 CE0 (GPIO 8) | SPI0 CE1 (GPIO 7) |
| SCLK / MOSI | GPIO 11 / GPIO 10 | shared |
| DC | GPIO 9 | GPIO 23 |
| RST | GPIO 25 | GPIO 24 |

DC on GPIO 9 reuses SPI0's MISO pin. That works because nothing is ever read back from the displays.

### Ears and head lamp (`body_io.py`, settings in `body_config.json`)

| Part | GPIO (BCM) | Header pin | Driver |
|---|---|---|---|
| Left ear servo (signal) | GPIO 12 | 32 | hardware PWM0 (`dtoverlay=pwm-2chan,...`) |
| Right ear servo (signal) | GPIO 13 | 33 | hardware PWM1 |
| Head lamp | GPIO 1 | 28 | on/off, lgpio software PWM for dimming |

- **Ears:**
  - Positions run -1..1: 1.5 ms ± 0.5 ms, the same as Open Duck Mini's `antennas.py`. Commands are clamped to `limit` (0.9).
  - `sign` and `trim` are per ear. Swap `gpio`/`pwm_channel` if left and right turn out to be the other way round.
  - Until the first command the servos get no pulses, so starting the service never moves them. `POST /ears/release` stops the pulses again.
  - Without the overlay, the ears fall back to lgpio software pulses (slight jitter).
  - Once the ears are in use they follow the expression (`"ears": [left, right]` in `expressions.json`).
- **Lamp:** `gpio=1=op,dl` keeps it off from power-up. `force_eeprom_read=0` stops the firmware's HAT-EEPROM probe on GPIO 0/1 from flickering it. The deploy script adds both lines to config.txt.
- **API (port 8100):**
  - `GET/POST /ears` (`{left, right}`)
  - `POST /ears/gesture` (`{name: wiggle|perk|droop|flick_left|flick_right|alert, times}`)
  - `POST /ears/idle` (`{enabled}`, random twitches)
  - `POST /ears/stop`, `POST /ears/release`
  - `GET/POST /lamp` (`{on, brightness}`)
  - `POST /lamp/blink` (`{times}`)
  - DCS proxies these as `/api/ears/*` and `/api/lamp/*`, and exposes them as MCP tools.

## Boot sequence

1. `duck-boot-status` starts early and draws two status panels. Text stays inside the central 170 px so the round edge doesn't clip it.
   - **Left eye (this Zero):**
     - hostname
     - USB link up
     - Wi-Fi/Tailscale IP
     - camera detected
   - **Right eye (the Pi 4, polled at `http://10.55.0.1:8000/api/companion/status`):**
     - DCS backend up
     - head servos found
     - mic and speaker
     - brain heartbeat from the laptop
2. Once the required checks pass (or after 180 s), it starts `duck-eyes`. The units `Conflicts=` each other, so the status screen releases SPI before the eyes take it.
3. `duck-eyes` pulls in `duck-headcam`. If `duck-eyes` crashes for good, `OnFailure=` brings the status screen back with the error. After 3 failures it stays on the status screen.

## Deploy

```bash
./scripts/deploy_head_zero.sh --host bdxmini.local          # first time: apt + venv + units
./scripts/deploy_head_zero.sh --host bdxmini.local --no-install   # fast redeploy
journalctl -fu duck-boot-status -u duck-eyes -u duck-headcam
```

Check the camera first with `rpicam-hello --list-cameras`.
