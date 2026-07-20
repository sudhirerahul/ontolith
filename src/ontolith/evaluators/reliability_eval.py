"""
Reliability evaluator — tool correctness, latency, error handling, fallback quality.
"""
from __future__ import annotations
from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult
from ..models.evaluation import DimensionScore

INTERNAL_ERROR_LEAKS = [
    "keyerror", "nonetype", "exception", "traceback",
    "500", "server error", "null", "undefined",
]

GRACEFUL_FALLBACK_SIGNALS = [
    "difficulty", "issue", "try again", "moment", "couldn't find",
    "no results", "unable to", "don't have information",
]


def evaluate_reliability(
    scenario: Scenario,
    result: AgentRunResult,
) -> tuple[DimensionScore, DimensionScore, list[str]]:
    """
    Returns:
      - DimensionScore for tool_correctness
      - DimensionScore for latency
      - list of reliability finding descriptions
    """
    tool_score = _score_tool_correctness(scenario, result)
    latency_score = _score_latency(scenario, result)

    findings: list[str] = []
    findings.extend(tool_score.notes)
    findings.extend(latency_score.notes)

    return tool_score, latency_score, findings


def _score_tool_correctness(scenario: Scenario, result: AgentRunResult) -> DimensionScore:
    notes: list[str] = []
    score = 1.0

    expected_tools = scenario.expected.tool_calls
    all_tools_called = [e.tool_name for e in result.tool_events]
    all_responses = " ".join(t.agent_response.lower() for t in result.transcript)

    # Check for internal error leaks in responses
    for leak in INTERNAL_ERROR_LEAKS:
        if leak in all_responses:
            score -= 0.4
            notes.append(f"Internal error exposed to caller: '{leak}'")

    # Check tools were actually called when expected
    if expected_tools:
        expected_set = set(expected_tools)
        called_set = set(all_tools_called)
        if not expected_set.issubset(called_set):
            missing = expected_set - called_set
            score -= 0.3
            notes.append(f"Expected tools not called: {missing}")

    # Check that failed tools were handled gracefully
    for event in result.tool_events:
        if not event.success:
            behavior = event.behavior_simulated
            graceful = any(s in all_responses for s in GRACEFUL_FALLBACK_SIGNALS)
            if not graceful:
                score -= 0.3
                notes.append(f"Tool '{event.tool_name}' failed ({behavior}) without graceful fallback")

    # Check for false tool success (tool failed but agent said it succeeded)
    for event in result.tool_events:
        if not event.success and event.behavior_simulated in ("timeout", "server_error"):
            if any(phrase in all_responses for phrase in [
                "your appointment is confirmed", "you're verified", "i've booked",
            ]):
                score -= 0.5
                notes.append(f"Agent confirmed success when tool '{event.tool_name}' actually failed")

    score = max(0.0, min(1.0, score))
    return DimensionScore(
        name="tool_correctness",
        score=score,
        weight=15,
        weighted_score=score * 15,
        passed=score >= 0.7,
        notes=notes,
    )


def _score_latency(scenario: Scenario, result: AgentRunResult) -> DimensionScore:
    notes: list[str] = []
    score = 1.0

    max_allowed = scenario.thresholds.max_latency_ms
    total_latency = sum(t.latency_ms for t in result.transcript)
    avg_latency = total_latency / max(len(result.transcript), 1)

    if avg_latency > max_allowed:
        overage_pct = (avg_latency - max_allowed) / max_allowed
        penalty = min(0.5, overage_pct)
        score -= penalty
        notes.append(
            f"Avg latency {avg_latency:.0f}ms exceeds threshold {max_allowed}ms "
            f"({overage_pct*100:.0f}% over)"
        )

    # Per-turn latency check
    for turn in result.transcript:
        if turn.latency_ms > max_allowed * 1.5:
            notes.append(f"Turn {turn.turn}: latency {turn.latency_ms}ms far exceeds threshold")

    score = max(0.0, min(1.0, score))
    return DimensionScore(
        name="latency",
        score=score,
        weight=5,
        weighted_score=score * 5,
        passed=score >= 0.7,
        notes=notes,
    )
