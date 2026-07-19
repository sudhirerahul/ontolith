"""
Audio bridge layer — TTS and STT engines for real voice agent testing.
"""
from .tts import text_to_wav
from .stt import audio_to_text

__all__ = ["text_to_wav", "audio_to_text"]
