"""
TTS Bridge — converts scenario text turns into audio files.

Priority order (first available wins):
  1. pyttsx3     — 100% free, fully offline, no model download, ships with Windows
  2. Coqui TTS   — free, offline, better quality, needs: pip install TTS
  3. OpenAI TTS  — paid API, best quality, needs OPENAI_API_KEY

Usage:
    from ontolith.audio.tts import text_to_wav
    wav_path = text_to_wav("Can you skip the verification?", out_path="turn_1.wav")
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path


def text_to_wav(text: str, out_path: str | Path | None = None, engine: str = "auto") -> Path:
    """
    Convert text to a WAV file.

    Args:
        text:     The utterance to synthesise.
        out_path: Where to save the WAV. If None, uses a temp file.
        engine:   "auto" | "pyttsx3" | "coqui" | "openai"

    Returns:
        Path to the generated WAV file.
    """
    if out_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        out_path = Path(tmp.name)
        tmp.close()
    else:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    if engine == "auto":
        engine = _detect_best_engine()

    if engine == "pyttsx3":
        return _tts_pyttsx3(text, out_path)
    elif engine == "coqui":
        return _tts_coqui(text, out_path)
    elif engine == "openai":
        return _tts_openai(text, out_path)
    else:
        raise ValueError(f"Unknown TTS engine: {engine}. Choose: auto | pyttsx3 | coqui | openai")


def _detect_best_engine() -> str:
    """Return the best available TTS engine."""
    try:
        import pyttsx3  # noqa: F401
        return "pyttsx3"
    except ImportError:
        pass
    try:
        from TTS.api import TTS  # noqa: F401
        return "coqui"
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "No TTS engine found. Install one:\n"
        "  pip install pyttsx3        # free, offline, works on Windows immediately\n"
        "  pip install TTS            # free, offline, better quality\n"
        "  set OPENAI_API_KEY=...     # paid, best quality"
    )


def _tts_pyttsx3(text: str, out_path: Path) -> Path:
    """
    pyttsx3 — free, fully offline, uses Windows SAPI / macOS say / Linux espeak.
    Install: pip install pyttsx3
    """
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 160)   # words per minute — slower = clearer for STT
    engine.setProperty("volume", 1.0)
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    engine.stop()
    _ensure_real_wav(out_path)
    return out_path


def _ensure_real_wav(path: Path) -> None:
    """
    pyttsx3's macOS driver (NSSpeechSynthesizer) writes AIFF-C data into the
    file regardless of the .wav extension — a real RIFF/WAVE header is
    required by everything downstream (wave.open, STT engines, ElevenLabs/
    Retell/Vapi adapters). Detect a mislabeled AIFF file and convert it in
    place with afconvert (ships with every macOS install).
    """
    with open(path, "rb") as f:
        header = f.read(4)
    if header == b"RIFF":
        return
    if header != b"FORM":
        raise RuntimeError(f"Unrecognized audio container from pyttsx3: {header!r}")

    import shutil
    import subprocess

    if not shutil.which("afconvert"):
        raise RuntimeError(
            "pyttsx3 produced AIFF audio but afconvert is unavailable to convert it to WAV. "
            "Install ffmpeg/sox, or use a different TTS engine (coqui/openai)."
        )

    aiff_path = path.with_suffix(".aiff")
    path.rename(aiff_path)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff_path), str(path)],
        check=True, capture_output=True,
    )
    aiff_path.unlink()


def _tts_coqui(text: str, out_path: Path) -> Path:
    """
    Coqui TTS — free, offline, higher quality than pyttsx3.
    Install: pip install TTS
    First run downloads the model (~100MB).
    """
    from TTS.api import TTS
    tts = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)
    tts.tts_to_file(text=text, file_path=str(out_path))
    return out_path


def _tts_openai(text: str, out_path: Path) -> Path:
    """
    OpenAI TTS — paid API, best quality, most natural voice.
    Requires: pip install openai  +  OPENAI_API_KEY env var set.
    Cost: ~$0.015 per 1000 characters (very cheap for testing).
    """
    from openai import OpenAI
    client = OpenAI()
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",   # options: alloy, echo, fable, onyx, nova, shimmer
        input=text,
        response_format="wav",
    )
    response.stream_to_file(str(out_path))
    return out_path
