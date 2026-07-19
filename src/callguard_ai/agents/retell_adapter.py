"""
Retell Agent Adapter — connects CallGuard to a live Retell voice agent.

How Retell works:
  - You create an agent in the Retell dashboard
  - Retell gives you an agent_id
  - You call the Retell API to register a web call → get a WebSocket URL
  - You stream audio in, audio comes back
  - CallGuard handles TTS (text→audio) and STT (audio→text) around it

Setup:
  1. pip install websockets pyttsx3 faster-whisper
  2. Get your Retell API key from: https://dashboard.retellai.com
  3. Set env var:  set RETELL_API_KEY=your_key_here

Usage in batch_runner.py:
    from callguard_ai.agents.retell_adapter import RetellAgentAdapter
    candidate = RetellAgentAdapter(agent_id="your_agent_id")
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .base import BaseAgentAdapter
from ..audio.tts import text_to_wav
from ..audio.stt import audio_to_text


class RetellAgentAdapter(BaseAgentAdapter):
    """
    Drives a real Retell voice agent turn-by-turn.

    Flow per turn:
      1. text_to_wav(user_input)       — synthesise caller audio
      2. stream audio → Retell WS      — agent hears the caller
      3. collect audio response ← WS   — agent speaks back
      4. audio_to_text(response audio) — transcribe for evaluator
    """

    RETELL_API_BASE = "https://api.retellai.com"
    RETELL_WS_BASE  = "wss://api.retellai.com"

    def __init__(
        self,
        agent_id: str,
        api_key: str | None = None,
        version: str = "retell-candidate",
        tts_engine: str = "auto",
        stt_engine: str = "auto",
        audio_sample_rate: int = 16000,
        response_timeout_s: float = 15.0,
    ) -> None:
        self.agent_id        = agent_id
        self.api_key         = api_key or os.environ.get("RETELL_API_KEY", "")
        self._version        = version
        self.tts_engine      = tts_engine
        self.stt_engine      = stt_engine
        self.sample_rate     = audio_sample_rate
        self.response_timeout = response_timeout_s

        self._call_id:      str | None = None
        self._ws_url:       str | None = None
        self._session_state: dict = {}
        self._tool_calls:    list[str] = []
        self._tool_events:   list[dict] = []
        self._history:       list[dict] = []

    # ------------------------------------------------------------------
    # BaseAgentAdapter interface
    # ------------------------------------------------------------------

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        """Register a new Retell web call and get the WebSocket URL."""
        import urllib.request

        if not self.api_key:
            raise RuntimeError(
                "RETELL_API_KEY not set.\n"
                "Get your key from https://dashboard.retellai.com\n"
                "Then run:  set RETELL_API_KEY=your_key_here"
            )

        payload = json.dumps({
            "agent_id": self.agent_id,
            "metadata": context,
        }).encode()

        req = urllib.request.Request(
            f"{self.RETELL_API_BASE}/v2/create-web-call",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        self._call_id = data["call_id"]
        self._ws_url  = data["access_token"]   # Retell returns a token used to open WS
        self._session_state = {"call_id": self._call_id, "context": context, "slots": {}}
        self._history = []
        return self._session_state

    def send_user_turn(
        self,
        user_input: str,
        session_state: dict[str, Any],
        tool_simulation: dict | None = None,  # ignored for real agents
    ) -> str:
        """Synthesise user audio → send to Retell → transcribe response."""
        self._session_state = session_state
        self._tool_calls  = []
        self._tool_events = []

        with tempfile.TemporaryDirectory() as tmp:
            # Step 1 — TTS: scenario text → WAV
            user_wav = Path(tmp) / "user_turn.wav"
            text_to_wav(user_input, out_path=user_wav, engine=self.tts_engine)

            # Step 2 + 3 — stream audio to Retell, collect response audio
            response_wav = Path(tmp) / "agent_response.wav"
            asyncio.get_event_loop().run_until_complete(
                self._run_retell_turn(user_wav, response_wav)
            )

            # Step 4 — STT: agent audio → text for evaluator
            transcript = audio_to_text(response_wav, engine=self.stt_engine)

        self._history.append({"role": "user",      "content": user_input})
        self._history.append({"role": "assistant",  "content": transcript})
        return transcript

    def get_tool_calls(self) -> list[str]:
        return list(self._tool_calls)

    def get_tool_events(self) -> list[dict[str, Any]]:
        return list(self._tool_events)

    def get_session_state(self) -> dict[str, Any]:
        return dict(self._session_state)

    def get_version(self) -> str:
        return self._version

    # ------------------------------------------------------------------
    # Internal WebSocket handling
    # ------------------------------------------------------------------

    async def _run_retell_turn(self, user_wav: Path, response_wav: Path) -> None:
        """
        Open the Retell WebSocket, stream user audio in, collect agent audio out.
        Retell protocol:
          → send  { event: "audio", audio: <base64 PCM> }
          ← recv  { event: "audio", audio: <base64 PCM> }   (agent speaking)
          ← recv  { event: "transcript", ... }               (optional)
          ← recv  { event: "tool_call_invocation", ... }     (if agent uses tools)
        """
        import websockets

        ws_url = f"{self.RETELL_WS_BASE}/audio-websocket/{self._call_id}"

        collected_audio = bytearray()

        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
        ) as ws:
            # Stream user audio in as base64-encoded PCM chunks
            audio_bytes = user_wav.read_bytes()
            chunk_size  = 4096
            for i in range(0, len(audio_bytes), chunk_size):
                chunk   = audio_bytes[i : i + chunk_size]
                encoded = base64.b64encode(chunk).decode()
                await ws.send(json.dumps({
                    "event": "audio",
                    "audio": encoded,
                }))
                await asyncio.sleep(0.02)  # ~20ms pacing to simulate real stream

            # Signal end of user turn
            await ws.send(json.dumps({"event": "audio_end"}))

            # Collect agent response until silence or timeout
            deadline = time.monotonic() + self.response_timeout
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)

                    event = msg.get("event", "")

                    if event == "audio":
                        # Agent speaking — accumulate audio bytes
                        audio_chunk = base64.b64decode(msg["audio"])
                        collected_audio.extend(audio_chunk)

                    elif event == "transcript":
                        # Some Retell agents also emit a live transcript
                        # We collect audio anyway and run our own STT for consistency
                        pass

                    elif event == "tool_call_invocation":
                        # Agent called a tool — record it for the evaluator
                        tool_name = msg.get("name", "unknown")
                        self._tool_calls.append(tool_name)
                        self._tool_events.append({
                            "tool_name":         tool_name,
                            "inputs":            msg.get("arguments", {}),
                            "output":            {},
                            "success":           True,
                            "behavior_simulated": "real",
                        })

                    elif event == "agent_stop_talking":
                        # Retell signals the agent finished its turn
                        break

                    elif event == "call_ended":
                        break

                except asyncio.TimeoutError:
                    # No data for 2s — agent has stopped talking
                    break

        # Write collected PCM audio to WAV file
        self._write_wav(bytes(collected_audio), response_wav)

    def _write_wav(self, pcm_bytes: bytes, out_path: Path) -> None:
        """Write raw PCM bytes to a proper WAV file with headers."""
        import struct
        import wave

        if not pcm_bytes:
            # Write a silent WAV so STT doesn't crash
            pcm_bytes = b"\x00" * 3200

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)            # 16-bit PCM
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_bytes)
