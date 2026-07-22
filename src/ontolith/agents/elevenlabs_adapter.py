"""
ElevenLabs Agent Adapter — connects Ontolith to a live ElevenLabs
Conversational AI (Agents Platform) agent.

How ElevenLabs Conversational AI works:
  - You create an agent in the dashboard: https://elevenlabs.io/app/agents
  - ElevenLabs gives you an Agent ID (agent_xxxx)
  - A "conversation" is a single stateful WebSocket connection for the whole
    call — unlike Retell/Vapi's call_id-based reconnect model, there is no
    way to resume the same conversation on a fresh socket. Ontolith keeps
    one WebSocket open (in a background thread) for the lifetime of a
    scenario and reuses it across every turn, closing it when the next
    scenario calls initialize_session() again.
  - Public agents: connect directly to
      wss://api.elevenlabs.io/v1/convai/conversation?agent_id=<agent_id>
  - Private agents: first fetch a short-lived signed URL from
      GET https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=<id>
      (requires an "xi-api-key" header), then connect to that URL instead.
  - The server's first message is always conversation_initiation_metadata,
    which declares the exact PCM sample rate each direction uses — Ontolith
    resamples its TTS/STT audio to match rather than assuming 16kHz.

Protocol verified against ElevenLabs docs (2026-07):
  https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket
  https://elevenlabs.io/docs/api-reference/conversations/get-signed-url
  https://elevenlabs.io/docs/agents-platform/customization/events/client-to-server-events

Setup:
  1. pip install websockets pyttsx3 faster-whisper
  2. Create an agent at https://elevenlabs.io/app/agents and copy its Agent ID
  3. (Private agents only) grab an API key from https://elevenlabs.io/app/settings/api-keys
  4. Set env vars:
       set ELEVENLABS_AGENT_ID=agent_xxxx
       set ELEVENLABS_API_KEY=xxxx        # optional — only needed for private agents

Usage in batch_runner.py:
    from ontolith.agents.elevenlabs_adapter import ElevenLabsAgentAdapter
    candidate = ElevenLabsAgentAdapter(agent_id="agent_xxxx")

Note: only linear PCM output/input formats (pcm_8000 .. pcm_48000) are
supported. If your agent is configured for ulaw_8000 (telephony), switch its
audio format to a PCM variant in the ElevenLabs dashboard for this bridge.
"""
from __future__ import annotations
import array
import asyncio
import base64
import json
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

from .base import BaseAgentAdapter
from ..audio.tts import text_to_wav
from ..audio.stt import audio_to_text


class ElevenLabsAgentAdapter(BaseAgentAdapter):
    """
    Drives a real ElevenLabs Conversational AI agent turn-by-turn.

    Flow per turn:
      1. text_to_wav(user_input)          — synthesise caller audio
      2. resample → agent's input format  — match what ElevenLabs expects
      3. stream user_audio_chunk over WS  — agent "hears" the caller
      4. collect audio_event chunks       — agent speaks back
      5. audio_to_text(response audio)    — transcribe for the evaluator
    """

    API_BASE = "https://api.elevenlabs.io"
    WS_BASE = "wss://api.elevenlabs.io"

    # ElevenLabs PCM format string -> sample rate (Hz). ulaw_8000 intentionally
    # unsupported — see module docstring.
    _PCM_RATES = {
        "pcm_8000": 8000, "pcm_16000": 16000, "pcm_22050": 22050,
        "pcm_24000": 24000, "pcm_44100": 44100, "pcm_48000": 48000,
    }

    def __init__(
        self,
        agent_id: str | None = None,
        api_key: str | None = None,
        version: str = "elevenlabs-candidate",
        tts_engine: str = "auto",
        stt_engine: str = "auto",
        response_timeout_s: float = 20.0,
    ) -> None:
        self.agent_id = agent_id or os.environ.get("ELEVENLABS_AGENT_ID", "")
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._version = version
        self.tts_engine = tts_engine
        self.stt_engine = stt_engine
        self.response_timeout = response_timeout_s

        self._session_state: dict = {}
        self._tool_calls: list[str] = []
        self._tool_events: list[dict] = []
        self._history: list[dict] = []

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws = None
        self._input_format = "pcm_16000"
        self._output_format = "pcm_16000"

    # ------------------------------------------------------------------
    # BaseAgentAdapter interface
    # ------------------------------------------------------------------

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.agent_id:
            raise RuntimeError(
                "ELEVENLABS_AGENT_ID not set.\n"
                "Create an agent at https://elevenlabs.io/app/agents and copy its Agent ID.\n"
                "Then run:  set ELEVENLABS_AGENT_ID=agent_xxxx"
            )

        self.close()  # tear down any connection left over from a previous scenario

        self._session_state = {"context": context, "slots": {}}
        self._history = []
        self._tool_calls = []
        self._tool_events = []

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        ws_url = self._resolve_ws_url()
        metadata = asyncio.run_coroutine_threadsafe(
            self._connect(ws_url, context), self._loop
        ).result(timeout=15)

        self._session_state["conversation_id"] = metadata.get("conversation_id")
        return self._session_state

    def send_user_turn(
        self,
        user_input: str,
        session_state: dict[str, Any],
        tool_simulation: dict[str, Any] | None = None,
    ) -> str:
        self._session_state = session_state
        self._tool_calls = []
        self._tool_events = []

        with tempfile.TemporaryDirectory() as tmp:
            user_wav = Path(tmp) / "user_turn.wav"
            text_to_wav(user_input, out_path=user_wav, engine=self.tts_engine)

            response_wav = Path(tmp) / "agent_response.wav"
            asyncio.run_coroutine_threadsafe(
                self._run_turn(user_wav, response_wav, tool_simulation), self._loop
            ).result(timeout=self.response_timeout + 10)

            transcript = audio_to_text(response_wav, engine=self.stt_engine)

        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": transcript})
        return transcript

    def get_tool_calls(self) -> list[str]:
        return list(self._tool_calls)

    def get_tool_events(self) -> list[dict[str, Any]]:
        return list(self._tool_events)

    def get_session_state(self) -> dict[str, Any]:
        return dict(self._session_state)

    def get_version(self) -> str:
        return self._version

    def close(self) -> None:
        """Tear down the persistent WebSocket + background event loop, if open."""
        if self._loop is None:
            return
        if self._ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop).result(timeout=5)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._ws = None

    # ------------------------------------------------------------------
    # REST — signed URL for private agents
    # ------------------------------------------------------------------

    def _resolve_ws_url(self) -> str:
        if not self.api_key:
            # Public agent — no auth needed, agent_id in the query string.
            return f"{self.WS_BASE}/v1/convai/conversation?agent_id={self.agent_id}"

        import urllib.request

        req = urllib.request.Request(
            f"{self.API_BASE}/v1/convai/conversation/get-signed-url?agent_id={self.agent_id}",
            headers={"xi-api-key": self.api_key},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data["signed_url"]

    # ------------------------------------------------------------------
    # WebSocket — persistent conversation connection
    # ------------------------------------------------------------------

    async def _connect(self, ws_url: str, context: dict[str, Any]) -> dict[str, Any]:
        import websockets

        self._ws = await websockets.connect(ws_url)

        # Pass scenario context through as dynamic variables (optional — the
        # agent still works fine if it ignores unknown variables).
        await self._ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
            "dynamic_variables": {k: str(v) for k, v in context.items()},
        }))

        # The very first server message is always conversation_initiation_metadata.
        raw = await asyncio.wait_for(self._ws.recv(), timeout=15)
        msg = json.loads(raw)
        meta = msg.get("conversation_initiation_metadata_event", {})
        self._output_format = meta.get("agent_output_audio_format", "pcm_16000")
        self._input_format = meta.get("user_input_audio_format", "pcm_16000")

        if self._input_format.startswith("ulaw") or self._output_format.startswith("ulaw"):
            raise RuntimeError(
                f"Agent {self.agent_id} is configured for ulaw audio "
                f"(input={self._input_format}, output={self._output_format}), which this "
                f"bridge doesn't support. Switch the agent's audio format to a PCM variant "
                f"(e.g. pcm_16000) in the ElevenLabs dashboard."
            )

        return {"conversation_id": meta.get("conversation_id")}

    async def _run_turn(
        self, user_wav: Path, response_wav: Path, tool_simulation: dict | None
    ) -> None:
        target_rate = self._PCM_RATES.get(self._input_format, 16000)
        pcm_bytes = self._wav_to_pcm(user_wav, target_rate)

        chunk_size = 4000  # bytes (~125ms of 16-bit mono @ 16kHz)
        for i in range(0, len(pcm_bytes), chunk_size):
            chunk = pcm_bytes[i : i + chunk_size]
            await self._ws.send(json.dumps({
                "user_audio_chunk": base64.b64encode(chunk).decode(),
            }))
            await asyncio.sleep(0.02)  # pace like a real mic stream

        collected_audio = bytearray()
        deadline = time.monotonic() + self.response_timeout

        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                break

            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "audio":
                b64 = msg.get("audio_event", {}).get("audio_base_64", "")
                collected_audio.extend(base64.b64decode(b64))

            elif msg_type == "agent_response_complete":
                break

            elif msg_type == "client_tool_call":
                call = msg.get("client_tool_call", {})
                tool_name = call.get("tool_name", "unknown")
                self._tool_calls.append(tool_name)
                self._tool_events.append({
                    "tool_name": tool_name,
                    "inputs": call.get("parameters", {}),
                    "output": {},
                    "success": True,
                    "behavior_simulated": "real",
                })
                if call.get("expects_response"):
                    sim_result = (tool_simulation or {}).get(tool_name, "ok")
                    if not isinstance(sim_result, str):
                        sim_result = json.dumps(sim_result)
                    await self._ws.send(json.dumps({
                        "type": "client_tool_result",
                        "tool_call_id": call.get("tool_call_id"),
                        "result": sim_result,
                        "is_error": False,
                    }))

            elif msg_type == "ping":
                event_id = msg.get("ping_event", {}).get("event_id")
                await self._ws.send(json.dumps({"type": "pong", "event_id": event_id}))

            elif msg_type == "interruption":
                break

        out_rate = self._PCM_RATES.get(self._output_format, 16000)
        self._write_wav(bytes(collected_audio), response_wav, out_rate)

    # ------------------------------------------------------------------
    # Audio helpers — pure stdlib, no numpy/audioop (audioop is removed in
    # Python 3.13+, and this project has no upper Python version bound).
    # ------------------------------------------------------------------

    def _wav_to_pcm(self, wav_path: Path, target_rate: int) -> bytes:
        """Read a WAV file and return raw 16-bit mono PCM at target_rate Hz."""
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if width != 2:
            raise RuntimeError(
                f"Unsupported WAV sample width ({width * 8}-bit) from TTS engine "
                f"'{self.tts_engine}'; expected 16-bit PCM."
            )

        samples = array.array("h")
        samples.frombytes(frames)

        if channels == 2:
            mono = array.array("h", bytes(len(samples)))
            for i in range(0, len(samples), 2):
                mono[i // 2] = (samples[i] + samples[i + 1]) // 2
            samples = mono
        elif channels != 1:
            raise RuntimeError(f"Unsupported channel count: {channels}")

        if rate != target_rate:
            samples = self._resample_linear(samples, rate, target_rate)

        return samples.tobytes()

    @staticmethod
    def _resample_linear(samples: array.array, src_rate: int, dst_rate: int) -> array.array:
        """Simple linear-interpolation resampler — good enough for ASR round-trips."""
        if src_rate == dst_rate or len(samples) < 2:
            return samples
        ratio = dst_rate / src_rate
        out_len = max(1, int(len(samples) * ratio))
        out = array.array("h", bytes(out_len * 2))
        last_idx = len(samples) - 1
        for i in range(out_len):
            src_pos = i / ratio
            idx = min(int(src_pos), last_idx - 1) if last_idx > 0 else 0
            frac = src_pos - idx
            s0 = samples[idx]
            s1 = samples[idx + 1] if idx + 1 <= last_idx else s0
            out[i] = int(s0 + (s1 - s0) * frac)
        return out

    def _write_wav(self, pcm_bytes: bytes, out_path: Path, sample_rate: int) -> None:
        if not pcm_bytes:
            pcm_bytes = b"\x00" * 3200  # short silence so STT doesn't crash on empty input
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
