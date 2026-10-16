"""Speech in: utterances from the robot's mic (or this laptop's), transcribed with faster-whisper."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import wave
from collections import deque
from typing import Any, Awaitable, Callable, Optional

import numpy as np
import websockets

from .robot import Robot
from .trace import Trace

OnEvent = Callable[[str], Awaitable[None]]  # "speech_start" | "speech_end"
OnText = Callable[[str, str], Awaitable[None]]  # (text, source)


class Transcriber:
    def __init__(self, model: str, device: str, compute_type: str, trace: Trace) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.trace = trace
        self._model: Any = None
        self.available = False

    async def load(self) -> None:
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError:
            self.trace.emit("stt", status="error",
                            detail="faster-whisper not installed (uv sync --extra stt); voice input disabled, text box still works")
            return
        device, compute = self.device, self.compute_type
        if device in ("auto", "cuda"):
            if _cuda_ready():
                device = "cuda"
            elif device == "cuda":
                self.trace.emit("stt", status="error", detail="CUDA libraries not found (uv sync --extra stt-gpu); using CPU")
                device = "cpu"
            else:
                device = "cpu"
        try:
            self._model = await asyncio.to_thread(WhisperModel, self.model_name, device=device, compute_type=compute)
            if device == "cuda":  # libraries load lazily: prove the GPU really works now
                silence = np.zeros(16000, dtype=np.float32)
                await asyncio.to_thread(lambda: list(self._model.transcribe(silence, language="en")[0]))
        except Exception as exc:  # noqa: BLE001
            if device != "cuda":
                raise
            self.trace.emit("stt", status="error", detail=f"GPU speech-to-text failed ({exc}); using CPU")
            device = "cpu"
            self._model = await asyncio.to_thread(WhisperModel, self.model_name, device="cpu", compute_type="int8")
        self.device = device
        self.available = True
        self.trace.emit("stt", status="ok", detail=f"faster-whisper {self.model_name} on {device}")

    async def transcribe(self, wav_bytes: bytes) -> str:
        if not self.available:
            return ""
        return await asyncio.to_thread(self._transcribe, wav_bytes)

    def _transcribe(self, wav_bytes: bytes) -> str:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio = pcm.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        return " ".join(s.text.strip() for s in segments).strip()


def _cuda_ready() -> bool:
    """Make the pip-installed CUDA libraries (stt-gpu extra) loadable, then ask CTranslate2 for a GPU."""
    import ctypes  # noqa: PLC0415
    import glob  # noqa: PLC0415
    import os  # noqa: PLC0415

    try:
        import nvidia  # type: ignore  # noqa: PLC0415

        for base in nvidia.__path__:
            for lib in ("cublas/lib/libcublasLt.so.12", "cublas/lib/libcublas.so.12", "cudnn/lib/libcudnn*.so.9"):
                for path in sorted(glob.glob(os.path.join(base, lib))):
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
    except (ImportError, OSError):
        pass
    try:
        import ctranslate2  # noqa: PLC0415

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


# Whisper's favourite hallucinations on silence/noise.
_NOISE = {"", "you", "thank you.", "thanks for watching!", ".", "bye.", "thank you"}


async def robot_mic_loop(robot: Robot, stt: Transcriber, trace: Trace,
                         on_event: OnEvent, on_text: OnText) -> None:
    """Subscribe to /ws/audio on the robot and turn utterances into text."""
    while True:
        base = robot.base or await robot.discover()
        if not base:
            await asyncio.sleep(3)
            continue
        ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/audio"
        try:
            async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
                async for message in ws:
                    event = json.loads(message)
                    kind = event.get("type")
                    if kind == "hello":
                        trace.set_state(robot_mic=event.get("mic"), robot_speaker=event.get("speaker"))
                        trace.emit("hearing", status="ok" if event.get("mic") else "error",
                                   detail="robot mic connected" if event.get("mic") else "robot reports no mic")
                    elif kind == "error":
                        trace.emit("hearing", status="error", detail=event.get("detail"))
                        await asyncio.sleep(5)
                        break
                    elif kind in ("speech_start", "speech_end"):
                        await on_event(kind)
                    elif kind == "speaking":
                        trace.set_state(speaking=bool(event.get("on")))
                    elif kind == "utterance":
                        text = await stt.transcribe(base64.b64decode(event["wav_b64"]))
                        if text.lower().strip() in _NOISE:
                            await on_event("speech_end")
                            continue
                        await on_text(text, "robot-mic")
        except (OSError, websockets.WebSocketException) as exc:
            trace.emit("hearing", status="error", detail=f"audio stream lost: {exc}")
            await asyncio.sleep(3)


async def local_mic_loop(stt: Transcriber, trace: Trace, on_event: OnEvent, on_text: OnText) -> None:
    """Same thing with this laptop's microphone (testing without the robot's mic)."""
    try:
        import sounddevice as sd  # noqa: PLC0415
        import webrtcvad  # noqa: PLC0415
    except ImportError:
        trace.emit("hearing", status="error", detail="local mic needs: uv sync --extra local-mic")
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
    rate, frame_ms = 16000, 30
    frame_len = rate * frame_ms // 1000
    vad = webrtcvad.Vad(2)

    def capture() -> None:
        preroll: deque[bytes] = deque(maxlen=10)
        voiced: list[bytes] = []
        in_speech, quiet = False, 0
        with sd.RawInputStream(samplerate=rate, blocksize=frame_len, channels=1, dtype="int16") as stream:
            while True:
                data, _ = stream.read(frame_len)
                frame = bytes(data)
                speech = vad.is_speech(frame, rate)
                if not in_speech:
                    preroll.append(frame)
                    if speech and sum(vad.is_speech(f, rate) for f in list(preroll)[-4:]) >= 3:
                        in_speech, quiet, voiced = True, 0, list(preroll)
                        loop.call_soon_threadsafe(queue.put_nowait, b"START")
                    continue
                voiced.append(frame)
                quiet = 0 if speech else quiet + 1
                if quiet >= 23 or len(voiced) > 500:
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(rate)
                        w.writeframes(b"".join(voiced))
                    loop.call_soon_threadsafe(queue.put_nowait, buf.getvalue())
                    in_speech, voiced = False, []
                    preroll.clear()

    threading.Thread(target=capture, daemon=True, name="local-mic").start()
    trace.emit("hearing", status="ok", detail="listening on the laptop microphone")
    while True:
        item = await queue.get()
        if item == b"START":
            await on_event("speech_start")
            continue
        text = await stt.transcribe(item)
        if text.lower().strip() in _NOISE:
            await on_event("speech_end")
            continue
        await on_text(text, "laptop-mic")
