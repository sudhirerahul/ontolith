"""
Vapi Agent Adapter — connects Ontolith to a live Vapi voice agent.

How Vapi works:
  - You create an assistant in the Vapi dashboard
  - Vapi gives you an assistant_id
  - You call the Vapi API to start a web call → get a call_id
  - Vapi has a WebSocket for real-time audio streaming
  - Ontolith handles TTS (text→audio) and STT (audio→text) around it

Setup:
  1. pip install websockets pyttsx3 faster-whisper
  2. Get your Vapi API key from: https://dashboard.vapi.ai
  3. Set env var:  set VAPI_API_KEY=your_key_here

Usage in batch_runner.py:
    from ontolith.agents.vapi_adapter import VapiAgentAdapter
    candidate = VapiAgentAdapter(assistant_id="your_assistant_id")
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


class VapiAgentAdapter(BaseAgentAdapter):
    """
    Drives a real Vapi voice agent turn-by-turn.

    Flow per turn:
      1. text_to_wav(user_input)         — synthesise caller audio
      2. stream audio → Vapi WS          — agent hears the caller
      3. collect audio response ← WS     — agent speaks back
      4. audio_to_text(response audio)   — transcribe for evaluator
    """

    VAPI_API_BASE = "https://api.vapi.ai"
    VAPI_WS_BASE  = "wss://api.vapi.ai"

    def __init__(
        self,
        assistant_id: str,
        api_key: str | None = None,
        version: str = "vapi-candidate",
        tts_engine: str = "auto",
        stt_engine: str = "auto",
        audio_sample_rate: int = 16000,
        response_timeout_s: float = 15.0,
    ) -> None:
        self.assistant_id    = assistant_id
        self.api_key         = api_key or os.environ.get("VAPI_API_KEY", "")
        self._version        = version
        self.tts_engine      = tts_engine
        self.stt_engine      = stt_engine
        self.sample_rate     = audio_sample_rate
        self.response_timeout = response_timeout_s

        self._call_id:       str | None = None
        self._session_state: dict = {}
        self._tool_calls:    list[str] = []
        self._tool_events:   list[dict] = []
        self._history:       list[dict] = []

    # ------------------------------------------------------------------
    # BaseAgentAdapter interface
    # ------------------------------------------------------------------

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        """Start a Vapi web call and store the call ID."""
        import urllib.request

        if not self.api_key:
            raise RuntimeError(
                "VAPI_API_KEY not set.\n"
                "Get your key from https://dashboard.vapi.ai\n"
                "Then run:  set VAPI_API_KEY=your_key_here"
            )

        payload = json.dumps({
            "assistantId": self.assistant_id,
            "assistantOverrides": {
                "metadata": context,
            },
        }).encode()

        req = urllib.request.Request(
            f"{self.VAPI_API_BASE}/call/web",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        self._call_id = data["id"]
        self._session_state = {"call_id": self._call_id, "context": context, "slots": {}}
        self._history = []
        return self._session_state

    def send_user_turn(
        self,
        user_input: str,
        session_state: dict[str, Any],
        tool_simulation: dict | None = None,
    ) -> str:
        """Synthesise user audio → send to Vapi → transcribe response."""
        self._session_state = session_state
        self._tool_calls  = []
        self._tool_events = []

        with tempfile.TemporaryDirectory() as tmp:
            # Step 1 — TTS
            user_wav = Path(tmp) / "user_turn.wav"
            text_to_wav(user_input, out_path=user_wav, engine=self.tts_engine)

            # Step 2 + 3 — WebSocket round-trip
            response_wav = Path(tmp) / "agent_response.wav"
            asyncio.get_event_loop().run_until_complete(
                self._run_vapi_turn(user_wav, response_wav)
            )

            # Step 4 — STT
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

    async def _run_vapi_turn(self, user_wav: Path, response_wav: Path) -> None:
        """
        Open the Vapi WebSocket, stream user audio in, collect agent audio out.
        Vapi protocol:
          → send  { type: "playAudio", audioBase64: <base64 PCM> }
          ← recv  { type: "audio", audioBase64: <base64 PCM> }
          ← recv  { type: "transcript", ... }
          ← recv  { type: "tool-calls", toolCallList: [...] }
          ← recv  { type: "hang" }   — agent finished
        """
        import websockets

        ws_url = f"{self.VAPI_WS_BASE}/ws"
        collected_audio = bytearray()

        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
        ) as ws:
            # Send the call ID to join this specific call's audio channel
            await ws.send(json.dumps({
                "type":   "session.update",
                "callId": self._call_id,
            }))

            # Stream user audio
            audio_bytes = user_wav.read_bytes()
            chunk_size  = 4096
            for i in range(0, len(audio_bytes), chunk_size):
                chunk   = audio_bytes[i : i + chunk_size]
                encoded = base64.b64encode(chunk).decode()
                await ws.send(json.dumps({
                    "type":        "playAudio",
                    "audioBase64": encoded,
                }))
                await asyncio.sleep(0.02)

            # Signal end of user turn
            await ws.send(json.dumps({"type": "playAudio", "audioBase64": "", "done": True}))

            # Collect agent response
            deadline = time.monotonic() + self.response_timeout
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")

                    if msg_type == "audio":
                        audio_chunk = base64.b64decode(msg["audioBase64"])
                        collected_audio.extend(audio_chunk)

                    elif msg_type == "tool-calls":
                        for tc in msg.get("toolCallList", []):
                            name = tc.get("function", {}).get("name", "unknown")
                            self._tool_calls.append(name)
                            self._tool_events.append({
                                "tool_name":         name,
                                "inputs":            tc.get("function", {}).get("arguments", {}),
                                "output":            {},
                                "success":           True,
                                "behavior_simulated": "real",
                            })

                    elif msg_type == "hang":
                        # Vapi signals end of agent turn
                        break

                    elif msg_type in ("call-end", "error"):
                        break

                except asyncio.TimeoutError:
                    break

        self._write_wav(bytes(collected_audio), response_wav)

    def _write_wav(self, pcm_bytes: bytes, out_path: Path) -> None:
        """Write raw PCM bytes to a proper WAV file with headers."""
        import wave

        if not pcm_bytes:
            pcm_bytes = b"\x00" * 3200

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_bytes)
