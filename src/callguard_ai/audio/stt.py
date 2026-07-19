"""
STT Bridge — transcribes agent audio responses back into text for evaluation.

Priority order (first available wins):
  1. faster-whisper  — free, offline, fast, good accuracy  (pip install faster-whisper)
  2. openai-whisper  — free, offline, original OpenAI model (pip install openai-whisper)
  3. OpenAI API STT  — paid, fastest, needs OPENAI_API_KEY

The evaluator always works on text — STT is the bridge that converts
your real agent's spoken response into something the evaluator can score.

Usage:
    from callguard_ai.audio.stt import audio_to_text
    transcript = audio_to_text("agent_response.wav")
"""
from __future__ import annotations
import os
from pathlib import Path


def audio_to_text(audio_path: str | Path, engine: str = "auto") -> str:
    """
    Transcribe a WAV/MP3 audio file to text.

    Args:
        audio_path: Path to the audio file from the agent.
        engine:     "auto" | "faster-whisper" | "whisper" | "openai"

    Returns:
        Transcribed text string.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if engine == "auto":
        engine = _detect_best_engine()

    if engine == "faster-whisper":
        return _stt_faster_whisper(audio_path)
    elif engine == "whisper":
        return _stt_whisper(audio_path)
    elif engine == "openai":
        return _stt_openai(audio_path)
    else:
        raise ValueError(f"Unknown STT engine: {engine}. Choose: auto | faster-whisper | whisper | openai")


def _detect_best_engine() -> str:
    """Return the best available STT engine."""
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return "whisper"
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "No STT engine found. Install one:\n"
        "  pip install faster-whisper   # free, offline, recommended\n"
        "  pip install openai-whisper   # free, offline, original\n"
        "  set OPENAI_API_KEY=...       # paid API fallback"
    )


def _stt_faster_whisper(audio_path: Path) -> str:
    """
    faster-whisper — free, runs offline, significantly faster than original Whisper.
    Install:  pip install faster-whisper
    First run downloads the model (~150MB for 'base', ~300MB for 'small').
    Model sizes: tiny | base | small | medium | large-v3
    """
    from faster_whisper import WhisperModel
    # 'base' is a good balance of speed vs accuracy for voice agent testing
    # Use 'small' or 'medium' for higher accuracy on accented/noisy audio
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), beam_size=5)
    return " ".join(seg.text.strip() for seg in segments).strip()


def _stt_whisper(audio_path: Path) -> str:
    """
    openai-whisper — free, offline, the original OpenAI Whisper model.
    Install:  pip install openai-whisper
    First run downloads the model (~140MB for 'base').
    """
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(str(audio_path))
    return result["text"].strip()


def _stt_openai(audio_path: Path) -> str:
    """
    OpenAI Whisper API — paid, no local model needed, fastest option.
    Requires: pip install openai  +  OPENAI_API_KEY env var set.
    Cost: $0.006 per minute of audio (very cheap for short agent turns).
    """
    from openai import OpenAI
    client = OpenAI()
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )
    return transcript.strip()
