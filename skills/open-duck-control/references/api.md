# DCS companion API reference

The base URL is the robot's Pi 4, for example `http://duckpi4.local:8000`. All bodies are JSON. MCP tool names match the
`operation_id`s below. The MCP endpoint is `/mcp` (streamable HTTP).

## Head (`head.control` node)

| MCP tool | REST | Body |
|---|---|---|
| `head_look_at` | `POST /api/head/look_at` | `{"yaw": 30, "pitch": -10, "roll": 0}` (roll optional) |
| `head_nod` | `POST /api/head/nod` | `{"times": 2}` |
| `head_shake` | `POST /api/head/shake` | `{"times": 2}` |
| `head_tilt` | `POST /api/head/tilt` | `{"angle": 15}` |
| `head_center` | `POST /api/head/center` | none |
| `head_stop` | `POST /api/head/stop` | none |
| `head_state` | `GET /api/head/state` | none |
| `head_idle_motion` | `POST /api/head/idle_motion` | `{"enabled": true, "breath_deg": 1.5, "sway_deg": 2}` |

Command responses:

```json
{"ok": true, "command": "look_at", "applied": {"head_yaw": 60.0, "head_pitch": 0.0},
 "clamped": true, "reasons": ["head_yaw 360 -> 60 deg (limit -60..60)"]}
```

`ok: false` means the command was rejected, for example by the rate limit or a non-numeric value. `reasons` says why.
`head_state` returns `command_deg`, `target_deg`, `present_deg`, `limits`, `queued`, `idle_motion` and `recent_events`.
All motion is eased: a critically damped spring with speed and acceleration caps, so frequent small targets blend into one smooth movement.

## Eyes (`eyes.link` node, proxied to the head Pi Zero)

| MCP tool | REST | Body |
|---|---|---|
| `eyes_list_expressions` | `GET /api/eyes/expressions` | none |
| `eyes_set_expression` | `POST /api/eyes/expression` | `{"name": "happy", "hold_s": 5}` |
| `eyes_look` | `POST /api/eyes/look` | `{"x": -0.5, "y": 0.2, "hold_s": 3}` |
| `eyes_blink` | `POST /api/eyes/blink` | none |
| `eyes_idle` | `POST /api/eyes/idle` | `{"enabled": true}` |
| `eyes_state` | `GET /api/eyes/state` | none |
| none | `GET /api/eyes/preview` | PNG of both eyes |

An unknown expression returns HTTP 400 listing the valid names. If the eyes are offline you get HTTP 503.

## Speech (`audio.io` node)

| MCP tool | REST | Body |
|---|---|---|
| `speech_say` | `POST /api/speech/say` | `{"text": "Hello!"}` (max 400 chars) |
| `speech_stop` | `POST /api/speech/stop` | none |
| none | `WS /ws/audio` | Events: `hello`, `speech_start`, `utterance` (base64 16 kHz WAV), `speech_end`, `speaking` |

## Safety and status

| MCP tool | REST | Notes |
|---|---|---|
| `estop` | `POST /api/estop` | Always allowed. Freezes the head, sets the eyes to neutral and stops speech |
| `companion_status` | `GET /api/companion/status` | `servos`, `eyes`, `audio`, `camera`, `brain` |

## Camera

The head camera publishes the stream `head_cam`:
- one JPEG frame: `GET /api/video/snapshot/head_cam`
- MJPEG: `GET /stream/video/head_cam`
