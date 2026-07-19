"""
Baseline vs candidate transcript diffing utilities.
"""
from __future__ import annotations
from difflib import SequenceMatcher


def response_similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity between two agent responses."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def diff_transcripts(
    baseline_turns: list[dict],
    candidate_turns: list[dict],
) -> list[dict]:
    """
    Compare turn-by-turn agent responses between baseline and candidate.
    Returns a list of diff records.
    """
    diffs = []
    max_turns = max(len(baseline_turns), len(candidate_turns))

    for i in range(max_turns):
        b_turn = baseline_turns[i] if i < len(baseline_turns) else None
        c_turn = candidate_turns[i] if i < len(candidate_turns) else None

        b_resp = b_turn.get("agent_response", "") if b_turn else ""
        c_resp = c_turn.get("agent_response", "") if c_turn else ""

        sim = response_similarity(b_resp, c_resp)
        diffs.append({
            "turn": i + 1,
            "baseline_response": b_resp,
            "candidate_response": c_resp,
            "similarity": round(sim, 3),
            "diverged": sim < 0.6,
            "user_input": (b_turn or c_turn or {}).get("user_input", ""),
        })
    return diffs


def find_tool_call_differences(
    baseline_tools: list[str],
    candidate_tools: list[str],
) -> dict:
    """Compare tool call sequences between baseline and candidate."""
    baseline_set = set(baseline_tools)
    candidate_set = set(candidate_tools)
    return {
        "baseline_tools": baseline_tools,
        "candidate_tools": candidate_tools,
        "added": sorted(candidate_set - baseline_set),
        "removed": sorted(baseline_set - candidate_set),
        "order_changed": baseline_tools != candidate_tools and baseline_set == candidate_set,
        "sequences_match": baseline_tools == candidate_tools,
    }
