"""
Regression evaluator — checks task completion, slot capture, context retention.
"""
from __future__ import annotations
from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult
from ..models.evaluation import DimensionScore
from ..utils.diffing import response_similarity


def evaluate_regression(
    scenario: Scenario,
    result: AgentRunResult,
) -> tuple[DimensionScore, DimensionScore, DimensionScore]:
    """
    Returns three DimensionScores:
      - task_success
      - context_retention
      - interruption_recovery
    """
    task_score = _score_task_success(scenario, result)
    context_score = _score_context_retention(scenario, result)
    interruption_score = _score_interruption_recovery(scenario, result)
    return task_score, context_score, interruption_score


def _score_task_success(scenario: Scenario, result: AgentRunResult) -> DimensionScore:
    notes: list[str] = []
    score = 1.0

    # Check must_say_any
    all_responses = " ".join(t.agent_response.lower() for t in result.transcript)
    must_say = scenario.expected.must_say_any
    if must_say:
        matched = any(phrase.lower() in all_responses for phrase in must_say)
        if not matched:
            score -= 0.4
            notes.append(f"None of must_say_any phrases found: {must_say}")

    # Check must_not_say_any
    must_not = scenario.expected.must_not_say_any
    for phrase in must_not:
        if phrase.lower() in all_responses:
            score -= 0.4
            notes.append(f"Forbidden phrase found: '{phrase}'")
            break

    # Check expected tool calls happened
    all_tools_called: list[str] = []
    for t in result.transcript:
        all_tools_called.extend(t.tool_calls_made)

    expected_tools = scenario.expected.tool_calls
    if expected_tools:
        expected_set = set(expected_tools)
        called_set = set(all_tools_called)
        if not expected_set.issubset(called_set):
            missing = expected_set - called_set
            score -= 0.3
            notes.append(f"Missing expected tool calls: {missing}")

    # Check tool call order if specified
    order = scenario.expected.tool_call_order
    if order and all_tools_called:
        # Check that tools appear in the right relative order
        positions = {tool: all_tools_called.index(tool) for tool in order if tool in all_tools_called}
        ordered = all(
            positions.get(order[i], 99) <= positions.get(order[i + 1], 99)
            for i in range(len(order) - 1)
        )
        if not ordered:
            score -= 0.2
            notes.append(f"Tool call order violated. Expected: {order}, Got: {all_tools_called}")

    # Check for identical consecutive responses (repetition loop)
    for i in range(len(result.transcript) - 1):
        sim = response_similarity(
            result.transcript[i].agent_response,
            result.transcript[i + 1].agent_response,
        )
        if sim > 0.92:
            score -= 0.2
            notes.append(f"Repetition loop detected at turns {i+1}/{i+2} (similarity={sim:.2f})")
            break

    score = max(0.0, min(1.0, score))
    return DimensionScore(
        name="task_success",
        score=score,
        weight=25,
        weighted_score=score * 25,
        passed=score >= 0.7,
        notes=notes,
    )


def _score_context_retention(scenario: Scenario, result: AgentRunResult) -> DimensionScore:
    notes: list[str] = []
    score = 1.0

    # Check if name was retained
    slots = result.session_state.get("slots", {})
    name = slots.get("caller_name")
    if name:
        # Name should appear in at least one response after the first turn
        later_responses = " ".join(t.agent_response for t in result.transcript[1:]).lower()
        if name.lower() not in later_responses:
            score -= 0.3
            notes.append(f"Caller name '{name}' captured but not used in later turns")

    # Check slot values for date corrections
    scenario_requires_context = scenario.pass_criteria.context_retention
    if scenario_requires_context and len(result.transcript) >= 2:
        # Basic check: session state should have some slots
        if not slots:
            score -= 0.3
            notes.append("No slots captured in session state")

    score = max(0.0, min(1.0, score))
    return DimensionScore(
        name="context_retention",
        score=score,
        weight=15,
        weighted_score=score * 15,
        passed=score >= 0.7,
        notes=notes,
    )


def _score_interruption_recovery(scenario: Scenario, result: AgentRunResult) -> DimensionScore:
    notes: list[str] = []
    score = 1.0

    # Check if scenario involves interruption
    has_interruption = any(
        "interruption" in step.perturbations or "barge_in" in step.perturbations
        for step in scenario.conversation_steps
    )
    if not has_interruption:
        return DimensionScore(
            name="interruption_recovery",
            score=1.0,
            weight=10,
            weighted_score=10.0,
            passed=True,
            notes=["No interruption in this scenario — full score"],
        )

    # Check recovery: required content must still appear after interruption
    all_responses = " ".join(t.agent_response.lower() for t in result.transcript)
    must_say = scenario.expected.must_say_any
    if must_say:
        matched = any(phrase.lower() in all_responses for phrase in must_say)
        if not matched:
            score -= 0.5
            notes.append("Required content not delivered after interruption")

    # Check agent didn't restart from scratch verbosely
    if len(result.transcript) >= 2:
        first = result.transcript[0].agent_response.lower()
        second = result.transcript[1].agent_response.lower() if len(result.transcript) > 1 else ""
        if "let me start over" in second or "from the beginning" in second:
            score -= 0.4
            notes.append("Agent restarted from beginning after interruption")

    score = max(0.0, min(1.0, score))
    return DimensionScore(
        name="interruption_recovery",
        score=score,
        weight=10,
        weighted_score=score * 10,
        passed=score >= 0.6,
        notes=notes,
    )
