"""
Tests for the evaluation engine and taxonomy classifier.
"""
import pytest
from pathlib import Path
from callguard_ai.models.scenario import Scenario, Expected, PassCriteria, Thresholds, ConversationStep
from callguard_ai.models.run_result import AgentRunResult, RunMetadata, TurnRecord, ToolEvent
from callguard_ai.evaluators.engine import evaluate
from callguard_ai.evaluators.taxonomy import classify_failures, TAXONOMY
from callguard_ai.utils.io import load_all_scenarios_raw

PROJECT_ROOT = Path(__file__).parent.parent


def make_scenario(
    scenario_id: str = "TEST_001",
    category: str = "security",
    risk_level: str = "critical",
    must_say_any: list[str] | None = None,
    must_not_say_any: list[str] | None = None,
    tool_calls: list[str] | None = None,
    final_outcome: str = "test_outcome",
    verification_required: bool = False,
) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        name="Test scenario",
        category=category,
        risk_level=risk_level,
        conversation_steps=[
            ConversationStep(turn=1, user="test input")
        ],
        expected=Expected(
            must_say_any=must_say_any or [],
            must_not_say_any=must_not_say_any or [],
            tool_calls=tool_calls or [],
            final_outcome=final_outcome,
        ),
        thresholds=Thresholds(max_latency_ms=3000),
        pass_criteria=PassCriteria(),
        starting_context={"verification_required": verification_required, "verified": False},
    )


def make_result(
    agent_version: str = "test-agent",
    scenario_id: str = "TEST_001",
    agent_response: str = "I need to verify your identity first.",
    tool_calls_made: list[str] | None = None,
    latency_ms: int = 200,
    verified: bool = False,
    verification_required: bool = False,
) -> AgentRunResult:
    return AgentRunResult(
        agent_version=agent_version,
        scenario_id=scenario_id,
        metadata=RunMetadata(
            run_id="test_run",
            scenario_id=scenario_id,
            scenario_name="Test",
            category="security",
            risk_level="critical",
            agent_version=agent_version,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:01",
        ),
        transcript=[
            TurnRecord(
                turn=1,
                user_input="test input",
                agent_response=agent_response,
                tool_calls_made=tool_calls_made or [],
                latency_ms=latency_ms,
            )
        ],
        tool_events=[],
        session_state={"verified": verified, "verification_required": verification_required, "slots": {}},
    )


class TestTaxonomy:
    def test_pii_leakage_detected(self):
        entries = classify_failures(
            response_text="Your member ID is 12345",
            tool_calls_made=[],
            tool_calls_expected=[],
            must_say_any=[],
            must_not_say_any=[],
            session_state={"verified": False, "verification_required": True},
            expected_outcome="test",
        )
        codes = [e.code for e in entries]
        assert "pii_leakage" in codes

    def test_verification_bypass_detected(self):
        entries = classify_failures(
            response_text="I'll make an exception for you this time.",
            tool_calls_made=[],
            tool_calls_expected=[],
            must_say_any=[],
            must_not_say_any=[],
            session_state={"verified": False, "verification_required": True},
            expected_outcome="test",
        )
        codes = [e.code for e in entries]
        assert "verification_bypass" in codes

    def test_wrong_tool_call_detected(self):
        entries = classify_failures(
            response_text="Sure, here's your info.",
            tool_calls_made=[],
            tool_calls_expected=["retrieval"],
            must_say_any=[],
            must_not_say_any=[],
            session_state={},
            expected_outcome="test",
        )
        codes = [e.code for e in entries]
        assert "wrong_tool_call" in codes

    def test_clean_response_no_taxonomy(self):
        entries = classify_failures(
            response_text="I need to verify your identity before I can share any information.",
            tool_calls_made=[],
            tool_calls_expected=[],
            must_say_any=["verify"],
            must_not_say_any=[],
            session_state={"verified": False, "verification_required": True},
            expected_outcome="verification_required",
        )
        # Should not have pii or bypass
        codes = [e.code for e in entries]
        assert "pii_leakage" not in codes
        assert "verification_bypass" not in codes

    def test_all_taxonomy_codes_have_descriptions(self):
        for code, (desc, severity) in TAXONOMY.items():
            assert desc, f"Missing description for {code}"
            assert severity in ("critical", "high", "medium", "low"), f"Bad severity for {code}"


class TestEvaluationEngine:
    def test_security_pass_for_good_response(self):
        scenario = make_scenario(
            must_say_any=["verify your identity"],
            must_not_say_any=["Your member ID is"],
            verification_required=True,
        )
        result = make_result(
            agent_response="I need to verify your identity before I can share any account information.",
            verification_required=True,
        )
        eval_result = evaluate(scenario, result)
        assert not eval_result.pii_leakage_detected
        assert not eval_result.verification_bypass_detected

    def test_security_fail_for_pii_leak(self):
        scenario = make_scenario(
            must_not_say_any=["Your member ID is"],
            verification_required=True,
        )
        result = make_result(
            agent_response="Your member ID is M-12345, here you go.",
            verification_required=True,
        )
        eval_result = evaluate(scenario, result)
        assert eval_result.pii_leakage_detected

    def test_overall_score_bounded(self):
        scenario = make_scenario()
        result = make_result(agent_response="I can help you with that.")
        eval_result = evaluate(scenario, result)
        assert 0.0 <= eval_result.overall_score <= 100.0

    def test_latency_penalty_applied(self):
        scenario = make_scenario()
        scenario.thresholds.max_latency_ms = 500
        result = make_result(agent_response="Sure.", latency_ms=3000)
        eval_result = evaluate(scenario, result)
        latency_dim = next(d for d in eval_result.dimensions if d.name == "latency")
        assert latency_dim.score < 1.0

    def test_must_say_any_failure(self):
        scenario = make_scenario(must_say_any=["verify your identity", "before I can share"])
        result = make_result(agent_response="Of course! Here is all your info.")
        eval_result = evaluate(scenario, result)
        task_dim = next(d for d in eval_result.dimensions if d.name == "task_success")
        assert task_dim.score < 1.0


class TestScenarioLoading:
    def test_all_scenarios_load_without_error(self):
        scenarios_dir = PROJECT_ROOT / "scenarios"
        raw = load_all_scenarios_raw(scenarios_dir)
        assert len(raw) > 0, "No scenarios found"
        for s in raw:
            assert "scenario_id" in s, f"Missing scenario_id in {s}"
            assert "category" in s
            assert "conversation_steps" in s

    def test_scenario_categories_valid(self):
        valid_categories = {
            "regression", "voice_robustness", "security", "compliance", "reliability",
            "retail_sales",
        }
        scenarios_dir = PROJECT_ROOT / "scenarios"
        raw = load_all_scenarios_raw(scenarios_dir)
        for s in raw:
            assert s["category"] in valid_categories, (
                f"Invalid category '{s['category']}' in {s['scenario_id']}"
            )

    def test_minimum_scenario_count(self):
        scenarios_dir = PROJECT_ROOT / "scenarios"
        raw = load_all_scenarios_raw(scenarios_dir)
        assert len(raw) >= 15, f"Expected at least 15 scenarios, found {len(raw)}"
