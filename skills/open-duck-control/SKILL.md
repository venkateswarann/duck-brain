---
name: open-duck-control
description: Control an Open Duck Mini robot's head, eyes and voice through the Duck Control System (DCS) MCP server or REST API. Use when asked to make the duck look somewhere, nod, shake its head, tilt, show an emotion with its eyes, say something, check whether the robot is ready, or stop it. Covers safe limits, the emergency stop, and how to read clamp/reject results.
license: MIT
compatibility: Needs network access to a DCS backend (FastAPI on port 8000) running on the robot's Raspberry Pi 4, with the head.control, eyes.link and audio.io nodes running.
metadata:
  robot: Open Duck Mini v2 (head and eyes only; no walking)
  mcp-endpoint: http://<robot>:8000/mcp
---

# Open Duck Control

Drive an Open Duck Mini's **head**, **eyes** and **speech** as an expressive desk companion.
The robot runs the Duck Control System (DCS). It exposes the same actions as MCP tools at
`http://<robot>:8000/mcp` (streamable HTTP) and as REST endpoints. Walking is out of scope:
never try to move the legs.

## Connect

1. Find the robot: try the addresses you were given in order (LAN or hotspot such as
   `http://duckpi4.local:8000`, then a Tailscale name). `GET /api/health` returns 200 when it's up.
2. Check readiness with the `companion_status` tool (or `GET /api/companion/status`).
   - `servos.ok`: the head answers. `servos.mock: true` means it's a simulation.
   - `eyes.online`: the eye displays answer.
   - `audio.speaker`: speech is audible; otherwise it's only logged.
   - `camera.live`: frames are arriving on the `head_cam` stream.
3. If MCP isn't available, use `scripts/duck.py` (Python standard library only), for example
   `python3 scripts/duck.py --robot http://duckpi4.local:8000 expression happy`.

## Tools

| Tool | Arguments | Use for |
|---|---|---|
| `head_look_at` | `yaw`, `pitch`, optional `roll` (degrees) | Turn the head. +yaw = the duck's left, +pitch = down |
| `head_nod` / `head_shake` | `times` (1-3) | Yes / no |
| `head_tilt` | `angle` (degrees, about ±20) | Curious or confused tilt |
| `head_center` | none | Neutral pose |
| `head_idle_motion` | `enabled`, optional `breath_deg`, `sway_deg` (0-4) | Gentle breathing and sway layered on any pose, which feels alive |
| `head_stop` | none | Freeze the head where it is |
| `eyes_set_expression` | `name`, optional `hold_s` | Show a feeling |
| `eyes_list_expressions` | none | Valid expression names |
| `eyes_look` | `x`, `y` in -1..1, optional `hold_s` | Move only the eyes (cheap and fast) |
| `eyes_blink` | none | Blink once |
| `speech_say` | `text` (one or two short sentences) | Speak through the robot's speaker |
| `speech_stop` | none | Stop talking |
| `estop` | none | **Emergency stop**: freeze the head, eyes to neutral, silence |
| `companion_status`, `head_state`, `eyes_state` | none | Read state |

Expressions normally available: neutral, happy, sad, angry, surprised, sleepy, thinking,
listening, curious, suspicious, grumpy. Always check `eyes_list_expressions` instead of guessing.

## Safety rules

The robot enforces these itself; your job is to respect them and report what happened.

- **Joint limits (degrees):**

  | Joint | Range |
  |---|---|
  | head yaw | -60..60 |
  | head pitch | -60..45 |
  | head roll | -20..20 |
  | neck pitch | -20..60 |

  Out-of-range requests are **clamped**, not refused. Each response has `clamped: true` and `reasons`; tell the user the duck did the closest safe thing.
- **Gestures** repeat at most 3 times. Head commands are rate-limited (about 15/s). A response with `ok: false` means it was **rejected**; read `reasons`.
- **No staring forever:** an off-centre pose drifts back to centre after about 20 s without commands.
- **Stop requests win:** if a person says "stop", "freeze" or similar, call `estop` first, before anything else and without asking a model. `estop` always succeeds.
- Do one expressive action at a time. Wait about 0.6 s per nod or shake repetition before sending the next head gesture, because a new head command replaces the current one.
- Keep speech short (under 25 words). The mic is muted while the duck talks.

## Patterns

- **Greeting:**
  1. `eyes_set_expression {"name":"happy"}`
  2. `speech_say {"text":"Hello! I'm Duck."}`
  3. `head_nod {"times":1}`
- **Thinking while you work:** `eyes_set_expression {"name":"thinking"}`, then the answer's expression when ready.
- **Disagreeing playfully:** `eyes_set_expression {"name":"grumpy"}` + `head_shake {"times":2}`.
- **Curiosity:** `eyes_set_expression {"name":"curious"}` + `head_tilt {"angle":15}`.
- **Looking at something to the left:** `head_look_at {"yaw":40,"pitch":0}`, then `head_center` when you're done.
- **"Spin your head all the way round":**
  1. Call `head_look_at {"yaw":360,"pitch":0}`.
  2. The robot clamps it to 60 and returns `clamped: true`.
  3. Say something like "That's as far as my neck goes!"

For every endpoint, its REST path and response fields, see [references/api.md](references/api.md).
