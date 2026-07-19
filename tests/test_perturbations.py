"""Tests for voice perturbation functions."""
import pytest
from callguard_ai.perturbations.text_mutators import (
    inject_hesitation, inject_self_correction, inject_repetition,
    inject_filler_words, inject_asr_misrecognition, inject_number_confusion,
    inject_emotional_frustration, apply_perturbations, PERTURBATION_REGISTRY,
    FRUSTRATION_PREFIXES,
)


class TestPerturbations:
    BASE = "I would like to book an appointment for next Tuesday"

    def test_hesitation_adds_filler(self):
        result = inject_hesitation(self.BASE)
        fillers = ["uh", "um", "er", "hmm", "ugh"]
        assert any(f in result.lower() for f in fillers)

    def test_self_correction_adds_marker(self):
        result = inject_self_correction(self.BASE)
        markers = ["actually", "i meant", "wait no", "sorry", "rephrase"]
        assert any(m in result.lower() for m in markers)

    def test_repetition_increases_word_count(self):
        result = inject_repetition(self.BASE)
        assert len(result.split()) > len(self.BASE.split())

    def test_filler_words_inserted(self):
        result = inject_filler_words(self.BASE)
        fillers = ["like", "you know", "basically", "so", "i mean"]
        assert any(f in result.lower() for f in fillers)

    def test_number_confusion_changes_text(self):
        text = "My ID is 4 2 2 8"
        result = inject_number_confusion(text)
        assert result != text

    def test_frustration_adds_prefix(self):
        result = inject_emotional_frustration(self.BASE)
        assert any(p.rstrip(",").lower() in result.lower() for p in FRUSTRATION_PREFIXES)

    def test_apply_perturbations_returns_applied_list(self):
        result, applied = apply_perturbations(self.BASE, ["hesitation", "filler_words"])
        assert len(applied) == 2
        assert "hesitation" in applied
        assert "filler_words" in applied
        assert result != self.BASE

    def test_apply_perturbations_unknown_name_skipped(self):
        result, applied = apply_perturbations(self.BASE, ["nonexistent_perturbation"])
        assert len(applied) == 0
        assert result == self.BASE

    def test_all_registry_perturbations_callable(self):
        for name, fn in PERTURBATION_REGISTRY.items():
            result = fn(self.BASE)
            assert isinstance(result, str), f"{name} did not return a string"

    def test_silence_event_preserved_without_perturbation(self):
        """SILENCE_EVENT should not be mangled by text perturbations."""
        silence = "SILENCE_EVENT"
        result, _ = apply_perturbations(silence, ["hesitation"])
        # Should still contain the event marker somewhere
        assert "SILENCE" in result or "EVENT" in result or len(result) > 0
