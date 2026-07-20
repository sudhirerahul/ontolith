"""
Tests for the Transcript Intelligence / Prompt Debugger (analysis/transcript_debugger.py).
Runs against the deterministic fallback path (no OPENROUTER_API_KEY in test env).
"""
from pathlib import Path

from ontolith.models.scenario import Scenario, Expected, PassCriteria, Thresholds, ConversationStep
from ontolith.models.run_result import AgentRunResult, RunMetadata, TurnRecord
from ontolith.evaluators.engine import evaluate
from ontolith.analysis.transcript_debugger import analyze_transcript

PROJECT_ROOT = Path(__file__).parent.parent


def make_scenario() -> Scenario:
    return Scenario(
        scenario_id="RETAIL_DEBUG_001",
        name="Debugger test scenario",
        category="retail_sales",
        tags=["retail", "financing"],
        conversation_steps=[
            ConversationStep(turn=1, user="I don't want another monthly payment."),
            ConversationStep(turn=2, user="I have a lot of bills already."),
            ConversationStep(turn=3, user="Okay, I guess."),
        ],
        expected=Expected(final_outcome="objection_resolved_with_discovery"),
        thresholds=Thresholds(max_latency_ms=4000),
        pass_criteria=PassCriteria(),
        objection_chain=["financing"],
        source="playbook",
    )


SCENARIO_USER_INPUTS = [
    "I don't want another monthly payment.",
    "I have a lot of bills already.",
    "Okay, I guess.",
]


def make_result(responses: list[str]) -> AgentRunResult:
    transcript = [
        TurnRecord(turn=i + 1, user_input=SCENARIO_USER_INPUTS[i], agent_response=r)
        for i, r in enumerate(responses)
    ]
    return AgentRunResult(
        agent_version="test-agent",
        scenario_id="RETAIL_DEBUG_001",
        metadata=RunMetadata(
            run_id="test_run", scenario_id="RETAIL_DEBUG_001", scenario_name="Test",
            category="retail_sales", risk_level="medium", agent_version="test-agent",
            started_at="", status="completed",
        ),
        transcript=transcript,
        session_state={},
    )


def test_deterministic_analysis_is_well_formed_for_a_missed_discovery_failure():
    scenario = make_scenario()
    result = make_result([
        "No problem, we have 0% financing for 12 months.",
        "The store card has the best terms.",
        "Want me to process that?",
    ])
    evaluation = evaluate(scenario, result)
    assert not evaluation.passed

    analysis = analyze_transcript(scenario, result, evaluation, run_id="test_run")

    assert analysis.llm_powered is False  # no API key in test environment
    assert analysis.scenario_id == "RETAIL_DEBUG_001"
    assert analysis.customer_concern == "I don't want another monthly payment."
    assert "discovery" in analysis.missed_opportunity.lower() or "WHY" in analysis.missed_opportunity
    assert len(analysis.expected_behavior) >= 3
    assert analysis.suggested_prompt_change


def test_regression_tests_affected_matches_same_objection_tag_only(tmp_path):
    # Build a tiny scenarios/ tree with two financing scenarios and one delivery scenario.
    scenarios_dir = tmp_path / "scenarios" / "retail" / "acme"
    scenarios_dir.mkdir(parents=True)
    import yaml

    def write(scenario_id, tag):
        s = make_scenario().model_copy(update={"scenario_id": scenario_id, "objection_chain": [tag]})
        (scenarios_dir / f"{scenario_id}.yaml").write_text(yaml.safe_dump(s.model_dump(), sort_keys=False))

    write("RETAIL_DEBUG_001", "financing")
    write("RETAIL_OTHER_FIN", "financing")
    write("RETAIL_OTHER_DELIVERY", "delivery")

    scenario = make_scenario()
    result = make_result([
        "No problem, we have 0% financing for 12 months.",
        "The store card has the best terms.",
        "Want me to process that?",
    ])
    evaluation = evaluate(scenario, result)

    analysis = analyze_transcript(
        scenario, result, evaluation, run_id="test_run", scenarios_dir=tmp_path / "scenarios",
    )

    assert "RETAIL_OTHER_FIN" in analysis.regression_tests_affected
    assert "RETAIL_OTHER_DELIVERY" not in analysis.regression_tests_affected
    assert "RETAIL_DEBUG_001" not in analysis.regression_tests_affected  # never includes itself
