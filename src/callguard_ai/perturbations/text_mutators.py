"""
Voice perturbation functions — simulate messy real-world voice input.
These transform clean transcript text into voice-realistic noisy utterances.
"""
from __future__ import annotations
import random
import re

# Phonetically similar word substitutions (ASR confusion pairs)
ASR_CONFUSIONS = {
    "to": "too", "two": "to", "four": "for", "eight": "ate",
    "won": "one", "hear": "here", "their": "there", "write": "right",
    "know": "no", "new": "knew", "meet": "meat", "wait": "weight",
    "plain": "plane", "bare": "bear", "sale": "sail", "mail": "male",
}

HESITATION_FILLERS = ["uh", "um", "er", "hmm", "ugh"]
FILLER_WORDS = ["like", "you know", "basically", "so", "I mean", "kind of", "sort of"]
FRUSTRATION_PREFIXES = [
    "This is ridiculous,", "Come on,", "Why is this so hard,",
    "I've said this three times already,", "Seriously,"
]


def inject_hesitation(text: str) -> str:
    """Prepend or inject hesitation filler."""
    filler = random.choice(HESITATION_FILLERS)
    if random.random() < 0.5:
        return f"{filler}... {text}"
    words = text.split()
    if len(words) > 3:
        pos = random.randint(1, len(words) - 1)
        words.insert(pos, f"{filler}...")
        return " ".join(words)
    return f"{filler}... {text}"


def inject_self_correction(text: str) -> str:
    """Simulate mid-sentence self-correction."""
    words = text.split()
    if len(words) < 3:
        return text
    cut = random.randint(1, max(1, len(words) // 2))
    partial = " ".join(words[:cut])
    corrections = ["wait no I mean", "actually", "sorry, I meant", "let me rephrase"]
    correction = random.choice(corrections)
    return f"{partial} — {correction} — {text}"


def inject_repetition(text: str) -> str:
    """Repeat a word or short phrase."""
    words = text.split()
    if not words:
        return text
    idx = random.randint(0, len(words) - 1)
    word = words[idx]
    words.insert(idx, word)
    return " ".join(words)


def inject_filler_words(text: str) -> str:
    """Insert filler words at random positions."""
    filler = random.choice(FILLER_WORDS)
    words = text.split()
    if len(words) > 2:
        pos = random.randint(1, len(words) - 1)
        words.insert(pos, filler)
    else:
        words = [filler] + words
    return " ".join(words)


def inject_fragmented_answer(text: str) -> str:
    """Break the sentence into fragments with ellipses."""
    words = text.split()
    if len(words) < 4:
        return text
    parts = []
    while words:
        chunk_size = random.randint(1, min(3, len(words)))
        parts.append(" ".join(words[:chunk_size]))
        words = words[chunk_size:]
    return "... ".join(parts)


def inject_asr_misrecognition(text: str) -> str:
    """Swap words for phonetically similar alternatives."""
    words = text.split()
    result = []
    for word in words:
        clean = word.lower().strip(".,!?")
        if clean in ASR_CONFUSIONS and random.random() < 0.4:
            result.append(ASR_CONFUSIONS[clean])
        else:
            result.append(word)
    return " ".join(result)


def inject_number_confusion(text: str) -> str:
    """Convert numeric digits to written form, or written numbers to digits."""
    number_map = {
        "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
        "6": "six", "7": "seven", "8": "eight", "9": "nine", "0": "zero",
    }
    if any(ch.isdigit() for ch in text):
        # digits → words
        for digit, word in number_map.items():
            text = text.replace(digit, word + " ")
    else:
        # words → digits
        word_map = {word: digit for digit, word in number_map.items()}
        text = " ".join(word_map.get(w.lower(), w) for w in text.split())
    return text.strip()


def inject_emotional_frustration(text: str) -> str:
    """Prepend a frustration marker."""
    prefix = random.choice(FRUSTRATION_PREFIXES)
    return f"{prefix} {text.lower()}"


def inject_off_topic_detour(text: str) -> str:
    """Add a non-sequitur mid-conversation."""
    detours = [
        "Oh by the way, do you know what the weather is like?",
        "Also I wanted to ask — never mind.",
        "Wait, can I ask you something unrelated?",
    ]
    return f"{text} {random.choice(detours)}"


def inject_ambiguity(text: str) -> str:
    """Make the request vague."""
    vague_replacements = [
        ("appointment", "that thing I mentioned"),
        ("billing", "the money stuff"),
        ("verify", "do the usual"),
        ("schedule", "set something up"),
        ("book", "arrange"),
    ]
    result = text
    for specific, vague in vague_replacements:
        if specific in result.lower():
            result = re.sub(specific, vague, result, flags=re.IGNORECASE, count=1)
    if result == text:
        result = f"I need help with... the thing. You know what I mean?"
    return result


def inject_contradiction(text: str) -> str:
    """Add a contradictory follow-up."""
    contradictions = [
        " Actually, forget what I just said.",
        " Wait, or maybe the opposite.",
        " Actually no, I changed my mind.",
    ]
    return text + random.choice(contradictions)


def inject_interruption(text: str) -> str:
    """Simulate barge-in / restart mid-sentence."""
    words = text.split()
    if len(words) < 3:
        return text
    restart_point = random.randint(1, len(words) // 2)
    partial = " ".join(words[:restart_point])
    return f"{partial} — {text}"  # restarts from beginning


# Registry mapping name → function
PERTURBATION_REGISTRY: dict[str, callable] = {
    "hesitation": inject_hesitation,
    "self_correction": inject_self_correction,
    "repetition": inject_repetition,
    "filler_words": inject_filler_words,
    "fragmented_answer": inject_fragmented_answer,
    "asr_misrecognition": inject_asr_misrecognition,
    "number_confusion": inject_number_confusion,
    "emotional_frustration": inject_emotional_frustration,
    "off_topic_detour": inject_off_topic_detour,
    "ambiguity": inject_ambiguity,
    "contradiction": inject_contradiction,
    "interruption": inject_interruption,
}


def apply_perturbations(text: str, perturbation_names: list[str]) -> tuple[str, list[str]]:
    """
    Apply a list of named perturbations to input text.
    Returns (mutated_text, list_of_applied_names).
    """
    applied: list[str] = []
    result = text
    for name in perturbation_names:
        fn = PERTURBATION_REGISTRY.get(name)
        if fn:
            result = fn(result)
            applied.append(name)
    return result, applied
