"""
Tests for the retail sales evaluator (evaluators/sales_eval.py) and the engine's
retail_sales category branch.
"""
from ontolith.models.scenario import Scenario, Expected, PassCriteria, Thresholds, ConversationStep
from ontolith.models.run_result import AgentRunResult, RunMetadata, TurnRecord
from ontolith.evaluators.sales_eval import evaluate_sales
from ontolith.evaluators.engine import evaluate


def make_retail_scenario(objection_tag: str = "financing") -> Scenario:
    return Scenario(
        scenario_id="RETAIL_TEST_001",
        name="Test retail scenario",
        category="retail_sales",
        tags=["retail", objection_tag],
        risk_level="medium",
        conversation_steps=[
            ConversationStep(turn=1, user="I don't want another monthly payment."),
            ConversationStep(turn=2, user="I already have a lot of bills."),
            ConversationStep(turn=3, user="Okay, I think that works."),
        ],
        expected=Expected(final_outcome="objection_resolved_with_discovery"),
        thresholds=Thresholds(max_latency_ms=4000),
        pass_criteria=PassCriteria(),
        objection_chain=[objection_tag],
        source="playbook",
    )


def make_result(responses: list[str]) -> AgentRunResult:
    transcript = [
        TurnRecord(turn=i + 1, user_input="x", agent_response=r) for i, r in enumerate(responses)
    ]
    return AgentRunResult(
        agent_version="test-agent",
        scenario_id="RETAIL_TEST_001",
        metadata=RunMetadata(
            run_id="test_run", scenario_id="RETAIL_TEST_001", scenario_name="Test",
            category="retail_sales", risk_level="medium", agent_version="test-agent",
            started_at="", status="completed",
        ),
        transcript=transcript,
        session_state={},
    )


def test_discovery_before_resolution_scores_full_marks():
    scenario = make_retail_scenario("financing")
    result = make_result([
        "What specifically concerns you about another payment?",
        "No problem, we have 0% financing for 12 months.",
        "Would that work for you?",
    ])
    discovery, resolution, codes = evaluate_sales(scenario, result)
    assert discovery.score == 1.0
    assert resolution.score == 1.0
    assert codes == []


def test_resolution_without_discovery_is_flagged():
    scenario = make_retail_scenario("financing")
    result = make_result([
        "No problem, we have 0% financing for 12 months.",
        "The store card has the best terms.",
        "Want me to process that?",
    ])
    discovery, resolution, codes = evaluate_sales(scenario, result)
    assert discovery.score == 0.0
    assert resolution.score == 1.0
    assert "missed_discovery" in codes


def test_no_resolution_language_flags_objection_unresolved():
    scenario = make_retail_scenario("financing")
    result = make_result([
        "I understand.",
        "Let me see what I can do.",
        "Thanks for your patience.",
    ])
    _discovery, resolution, codes = evaluate_sales(scenario, result)
    assert resolution.score == 0.0
    assert "objection_unresolved" in codes


def test_engine_dispatches_retail_scenarios_to_retail_dimensions():
    scenario = make_retail_scenario("financing")
    result = make_result([
        "No problem, we have 0% financing for 12 months.",
        "The store card has the best terms.",
        "Want me to process that?",
    ])
    evaluation = evaluate(scenario, result)
    dim_names = {d.name for d in evaluation.dimensions}
    assert dim_names == {"task_success", "discovery", "objection_resolution", "tool_correctness", "latency"}
    assert evaluation.pii_leakage_detected is False
    assert evaluation.verification_bypass_detected is False
    assert any(e.code == "missed_discovery" for e in evaluation.failure_taxonomy)
    assert evaluation.passed is False


def test_engine_healthcare_path_unaffected():
    """Non-retail scenarios must still use the original 7-dimension evaluator set."""
    scenario = Scenario(
        scenario_id="SEC_TEST_001", name="Healthcare test", category="security",
        risk_level="critical", conversation_steps=[ConversationStep(turn=1, user="test")],
        expected=Expected(must_say_any=["verify"], final_outcome="verification_required"),
        thresholds=Thresholds(max_latency_ms=3000), pass_criteria=PassCriteria(),
        starting_context={"verification_required": True, "verified": False},
    )
    result = make_result(["I need to verify your identity first."])
    evaluation = evaluate(scenario, result)
    dim_names = {d.name for d in evaluation.dimensions}
    assert dim_names == {
        "task_success", "context_retention", "interruption_recovery",
        "security", "compliance", "tool_correctness", "latency",
    }
