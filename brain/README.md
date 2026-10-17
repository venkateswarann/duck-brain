# Duck Brain

An offline, open-weight AI brain for an [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini)
desk companion. It listens, looks, remembers people, and answers with eye expressions, head gestures
and speech. All decisions are made by **Gemma 4** running locally. No cloud calls.

## Model

| | |
|---|---|
| Model | **Gemma 4 E2B** (`gemma4:e2b`, open weights, multimodal: chat + camera vision in one model) by Google DeepMind |
| Runtime | [Ollama](https://ollama.com/library/gemma4), running locally on the laptop |
| Licence / terms | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) · [Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`small.en`, MIT) running Whisper weights (MIT) |
| Text-to-speech | [Piper](https://github.com/rhasspy/piper) (MIT) on the robot |

## What the AI does

Gemma is the decision-maker for every reply. For each thing it hears or sees, it returns **structured
JSON**, constrained by an Ollama JSON schema:

```json
{"say": "Mondays are awfully suspicious.", "expression": "suspicious",
 "gestures": [{"tool": "tilt_head", "args": {"angle": 15}}], "remember": []}
```

The harness (this package) then:

1. **Safety layer** (`safety.py`) checks each action:
   - Unknown tools are blocked.
   - Head angles are clamped to the robot's own limits.
   - Repetitions and hold times are capped.
   - There are at most 3 gestures per reply.

   A spoken stop word ("stop", "duck stop", "freeze") triggers the e-stop **without going through the model**.
2. **Acts** by calling **MCP tools** on the robot's DCS server (`/mcp`): `eyes_set_expression`, `speech_say`,
   `head_nod`, … The robot clamps again on its side, so a wrong decision can never exceed the limits.
3. **Remembers** names and facts in `memory.json` and feeds a summary back into the prompt.
4. **Sees:** questions like "what am I holding?" attach a frame from the head camera, using Gemma's vision.
5. **Reflexes** run without the LLM:
   - Faces are tracked with OpenCV, and the eyes and head follow them.
   - The eyes switch to `listening` as soon as speech starts and to `thinking` while Gemma decides.
   - A new face triggers a greeting.

Every step appears live in the **trace UI** (http://127.0.0.1:8300): what was heard, Gemma's raw JSON,
each MCP tool call, and blocked or clamped actions in red/amber with their reasons.

```
 robot USB mic ─► /ws/audio ─► faster-whisper ─┐
 head camera  ─► /api/video/snapshot ─┬────────┤
                                      │        ▼
                         face tracker │   Gemma 4 E2B (Ollama, JSON schema)
                       (reflex, REST) │        │
                                      │        ▼
                                      │   safety layer ── stop word ─► estop
                                      │        │
                                      ▼        ▼
                          DCS on the Pi 4: /api (reflexes) + /mcp (decisions)
                          head servos · eyes (Pi Zero) · speaker (Piper)
```

## Run

```bash
cd brain
uv sync --extra stt                 # add --extra local-mic to use the laptop's mic
ollama pull gemma4:e2b
# set robot.urls in config.yaml (LAN/hotspot name first, Tailscale name second)
uv run duck-brain                   # trace UI on http://127.0.0.1:8300
```

Useful flags:
- `--source text` makes the trace UI's text box the only input.
- `--source local` uses the laptop's mic.
- `--robot-url http://127.0.0.1:8000` targets a local mock DCS.
- `--no-tracking` turns off face tracking.

Tests: `uv run pytest`.

### Without the robot (everything on one PC)

```bash
# 1. eyes service, rendering only
cd devices/head_zero && python3 eyes_server.py --mock --port 8100
# 2. DCS backend in mock mode (set companion.eyes_urls to http://127.0.0.1:8100 and mock_hardware true)
cd backend && DCS_CONFIG=/path/to/test_config.json .venv/bin/uvicorn app.main:app --port 8000
# 3. fake head camera
cd devices/head_zero && python3 head_camera.py --mock --dcs http://127.0.0.1:8000
# 4. the brain
cd brain && uv run duck-brain --source text --robot-url http://127.0.0.1:8000
```

## Tuning

`config.yaml` has these knobs:
- tracking signs: `yaw_sign`, `pitch_sign` and `eyes_x_sign`. Flip one if the duck looks away from you.
- camera field of view
- stop words
- safety caps
- vision trigger words
- Ollama options: `num_predict` keeps replies short.
