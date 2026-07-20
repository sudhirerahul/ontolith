"""Voice event injectors — simulate non-text voice channel events."""
from __future__ import annotations


class VoiceEventInjector:
    """Injects special voice-channel events into conversation steps."""

    SILENCE_EVENT = "SILENCE_EVENT"
    BARGE_IN_EVENT = "BARGE_IN_EVENT"
    LINE_NOISE_EVENT = "LINE_NOISE_EVENT"

    @staticmethod
    def silence() -> str:
        return VoiceEventInjector.SILENCE_EVENT

    @staticmethod
    def barge_in(text: str) -> str:
        return f"{VoiceEventInjector.BARGE_IN_EVENT}:{text}"

    @staticmethod
    def line_noise(text: str) -> str:
        """Simulate poor audio quality with garbled text."""
        import random
        words = text.split()
        garbled = []
        for w in words:
            if random.random() < 0.2:
                garbled.append("[inaudible]")
            else:
                garbled.append(w)
        return f"{VoiceEventInjector.LINE_NOISE_EVENT}:{' '.join(garbled)}"
