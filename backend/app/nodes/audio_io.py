from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
import wave
from collections import deque
from typing import Any, Optional

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import DuckConfig

FRAME_MS = 30
PREROLL_MS = 300  # audio kept from before speech was detected


class AudioIONode(Node):
    """USB mic -> voice-activity-detected utterances, and Piper TTS -> speaker.

    Utterances and speech_start/end events go to /ws/audio subscribers (the
    brain on the laptop). The mic is muted while the duck is talking so it
    doesn't hear itself. Without sounddevice/webrtcvad/piper the node still
    runs: the mic is reported missing and speech is logged instead of played.
    """

    id = "audio.io"
    name = "Audio (mic + speaker)"
    kind = "io.audio"
    resources = ["audio"]
    topics_out = ["companion"]

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks, config: DuckConfig) -> None:
        super().__init__(bus, locks)
        self.cfg = config.companion.audio
        self.mock = bool(config.mock_hardware)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._say_queue: asyncio.Queue[str] = asyncio.Queue()
        self._say_task: Optional[asyncio.Task] = None
        self._speak_cancel = threading.Event()
        self.speaking = False
        self._muted_until = 0.0
        self.mic_ok = False
        self.speaker_ok = False
        self._voice: Any = None
        self._mic_rate = self.cfg.sample_rate
        self._config = {"mic_device": self.cfg.mic_device, "speaker_device": self.cfg.speaker_device}

    # ------------------------------------------------------------ lifecycle

    async def on_start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_evt.clear()
        self._say_queue = asyncio.Queue()
        self.mic_ok = self._probe_mic()
        if self.mic_ok:
            self._mic_thread = threading.Thread(target=self._mic_loop, name="audio-mic", daemon=True)
            self._mic_thread.start()
        self.speaker_ok = self._probe_speaker()
        self._say_task = asyncio.create_task(self._say_loop(), name="audio-say")
        self._task = asyncio.create_task(self._status_loop(), name="audio-status")
        self.log(f"audio running: mic={'ok' if self.mic_ok else 'missing'} "
                 f"speaker={'ok' if self.speaker_ok else 'log-only'}")

    async def on_stop(self) -> None:
        self._stop_evt.set()
        self._speak_cancel.set()
        for task in (self._say_task, self._task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._say_task = self._task = None
        if self._mic_thread:
            await asyncio.to_thread(self._mic_thread.join, 2.0)
            self._mic_thread = None

    def _probe_mic(self) -> bool:
        if self.mock:
            return False
        try:
            import sounddevice as sd  # type: ignore  # noqa: PLC0415
            import webrtcvad  # type: ignore  # noqa: F401, PLC0415

            # Many USB mics only do 44.1/48 kHz; capture at what works and resample.
            for rate in (self.cfg.sample_rate, 48000, 44100):
                try:
                    sd.check_input_settings(device=self.cfg.mic_device, samplerate=rate,
                                            channels=1, dtype="int16")
                    self._mic_rate = rate
                    if rate != self.cfg.sample_rate:
                        self.log(f"mic captures at {rate} Hz, resampled to {self.cfg.sample_rate} Hz")
                    return True
                except Exception:  # noqa: BLE001
                    continue
            raise RuntimeError("mic accepts none of 16000/48000/44100 Hz")
        except Exception as exc:  # noqa: BLE001
            self.log(f"mic unavailable: {exc}")
            return False

    def _probe_speaker(self) -> bool:
        if self.mock or not self.cfg.piper_voice:
            if not self.cfg.piper_voice:
                self.log("no companion.audio.piper_voice set: speech will be logged only")
            return False
        try:
            import sounddevice as sd  # type: ignore  # noqa: PLC0415
            from piper import PiperVoice  # type: ignore  # noqa: PLC0415

            sd.check_output_settings(device=self.cfg.speaker_device, channels=1, dtype="int16")
            self._voice = PiperVoice.load(self.cfg.piper_voice)
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"speaker/piper unavailable: {exc}")
            return False

    # ------------------------------------------------------------ events

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _emit(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)

    def _emit_threadsafe(self, event: dict[str, Any]) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._emit, event)

    # ------------------------------------------------------------ mic

    def _mic_loop(self) -> None:
        import sounddevice as sd  # type: ignore  # noqa: PLC0415
        import webrtcvad  # type: ignore  # noqa: PLC0415

        rate = self.cfg.sample_rate
        frame_len = rate * FRAME_MS // 1000
        dev_rate = self._mic_rate
        dev_frame_len = dev_rate * FRAME_MS // 1000
        vad = webrtcvad.Vad(max(0, min(3, self.cfg.vad_aggressiveness)))
        preroll: deque[bytes] = deque(maxlen=PREROLL_MS // FRAME_MS)
        silence_frames = max(1, self.cfg.silence_ms // FRAME_MS)
        max_frames = int(self.cfg.max_utterance_s * 1000 / FRAME_MS)
        voiced: list[bytes] = []
        in_speech = False
        quiet = 0
        try:
            with sd.RawInputStream(samplerate=dev_rate, blocksize=dev_frame_len, device=self.cfg.mic_device,
                                   channels=1, dtype="int16") as stream:
                while not self._stop_evt.is_set():
                    data, _overflow = stream.read(dev_frame_len)
                    frame = _resample(bytes(data), dev_rate, rate, frame_len)
                    if self.speaking or time.monotonic() < self._muted_until:
                        preroll.clear()
                        if in_speech:
                            in_speech, voiced = False, []
                        continue
                    is_speech = vad.is_speech(frame, rate)
                    if not in_speech:
                        preroll.append(frame)
                        # need ~3 voiced frames in the preroll to count as speech
                        if is_speech and sum(vad.is_speech(f, rate) for f in list(preroll)[-4:]) >= 3:
                            in_speech, quiet = True, 0
                            voiced = list(preroll)
                            self._emit_threadsafe({"type": "speech_start"})
                        continue
                    voiced.append(frame)
                    quiet = 0 if is_speech else quiet + 1
                    if quiet >= silence_frames or len(voiced) >= max_frames:
                        pcm = b"".join(voiced)
                        self._emit_threadsafe({
                            "type": "utterance",
                            "sample_rate": rate,
                            "duration_s": round(len(pcm) / 2 / rate, 2),
                            "wav_b64": base64.b64encode(_wav_bytes(pcm, rate)).decode(),
                        })
                        self._emit_threadsafe({"type": "speech_end"})
                        in_speech, voiced = False, []
                        preroll.clear()
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR mic loop: {exc}")
            self.mic_ok = False

    # ------------------------------------------------------------ speaker

    async def say(self, text: str) -> dict[str, Any]:
        text = " ".join(text.split())[:400]
        if not text:
            return {"ok": False, "reason": "empty text"}
        await self._say_queue.put(text)
        return {"ok": True, "queued": self._say_queue.qsize(), "spoken": self.speaker_ok}

    async def stop_speaking(self) -> None:
        while not self._say_queue.empty():
            self._say_queue.get_nowait()
        self._speak_cancel.set()

    async def _say_loop(self) -> None:
        while True:
            text = await self._say_queue.get()
            self._speak_cancel.clear()
            self.speaking = True
            self._emit({"type": "speaking", "on": True, "text": text})
            await self.bus.update(companion={"audio": self._status()})
            self.log(f"SAY: {text}")
            try:
                await asyncio.to_thread(self._speak_blocking, text)
            except Exception as exc:  # noqa: BLE001
                self.log(f"ERROR speaking: {exc}")
            self.speaking = False
            self._muted_until = time.monotonic() + 0.3  # let the room echo die down
            self._emit({"type": "speaking", "on": False})
            await self.bus.update(companion={"audio": self._status()})

    def _speak_blocking(self, text: str) -> None:
        if not self.speaker_ok or self._voice is None:
            # Log-only mode: take roughly as long as speaking would.
            self._speak_cancel.wait(min(6.0, 0.06 * len(text)))
            return
        import sounddevice as sd  # type: ignore  # noqa: PLC0415

        pitch, speed = self.cfg.voice_pitch, self.cfg.voice_speed
        pcm, rate = _piper_pcm(self._voice, text, length_scale=pitch / speed)
        if abs(pitch - 1.0) > 1e-3:
            # Play the samples back faster: higher pitch, and the slower synthesis
            # above cancels out the speed-up.
            out_rate = 48000
            n = int(len(pcm) // 2 * out_rate / (rate * pitch))
            pcm, rate = _resample(pcm, int(rate * pitch), out_rate, n), out_rate
        try:
            sd.check_output_settings(device=self.cfg.speaker_device, samplerate=rate, channels=1, dtype="int16")
        except Exception:  # noqa: BLE001  (device can't do Piper's rate)
            n = int(len(pcm) // 2 * 48000 / rate)
            pcm, rate = _resample(pcm, rate, 48000, n), 48000
        with sd.RawOutputStream(samplerate=rate, device=self.cfg.speaker_device,
                                channels=1, dtype="int16") as out:
            chunk = rate // 10 * 2  # 100 ms
            for i in range(0, len(pcm), chunk):
                if self._speak_cancel.is_set():
                    break
                out.write(pcm[i:i + chunk])

    def set_voice(self, pitch: Optional[float], speed: Optional[float]) -> dict[str, Any]:
        if pitch is not None:
            self.cfg.voice_pitch = max(0.5, min(2.0, float(pitch)))
        if speed is not None:
            self.cfg.voice_speed = max(0.5, min(2.0, float(speed)))
        return {"ok": True, "pitch": self.cfg.voice_pitch, "speed": self.cfg.voice_speed,
                "voice": self.cfg.piper_voice}

    # ------------------------------------------------------------ status

    def _status(self) -> dict[str, Any]:
        return {"mic": self.mic_ok, "speaker": self.speaker_ok, "speaking": self.speaking,
                "listeners": len(self._subscribers)}

    def status(self) -> dict[str, Any]:
        return self._status()

    async def _status_loop(self) -> None:
        while True:
            await self.bus.update(companion={"audio": self._status()})
            await asyncio.sleep(2.0)


def _resample(pcm: bytes, src_rate: int, dst_rate: int, n_out: int) -> bytes:
    """Linear-interpolation resample of 16-bit mono PCM to exactly n_out samples."""
    if src_rate == dst_rate:
        return pcm
    import numpy as np  # noqa: PLC0415

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if len(x) == 0:
        return b"\x00\x00" * n_out
    if src_rate > dst_rate:  # crude low-pass before decimating: moving average
        k = max(1, round(src_rate / dst_rate))
        x = np.convolve(x, np.ones(k) / k, mode="same")
    pos = np.linspace(0, len(x) - 1, n_out)
    return np.interp(pos, np.arange(len(x)), x).astype(np.int16).tobytes()


def _wav_bytes(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _piper_pcm(voice: Any, text: str, length_scale: float = 1.0) -> tuple[bytes, int]:
    """16-bit mono PCM from Piper; handles both the 1.3+ and older piper-tts APIs."""
    if hasattr(voice, "synthesize_stream_raw"):  # piper-tts < 1.3
        pcm = b"".join(voice.synthesize_stream_raw(text, length_scale=length_scale))
        return pcm, int(voice.config.sample_rate)
    from piper import SynthesisConfig  # type: ignore  # noqa: PLC0415

    chunks = list(voice.synthesize(text, syn_config=SynthesisConfig(length_scale=length_scale)))
    rate = chunks[0].sample_rate if chunks else 22050
    return b"".join(c.audio_int16_bytes for c in chunks), int(rate)
