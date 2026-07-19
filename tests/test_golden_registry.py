"""
Tests for the golden dataset workflow: import -> pending -> approve -> auto-pickup,
and the verified/regressed state machine (registry.py, transcript_intake.py).
"""
import json
from pathlib import Path

import pytest

from callguard_ai.golden.registry import GoldenRegistry
from callguard_ai.golden.transcript_intake import import_customer_transcript
from callguard_ai.utils.io import load_all_scenarios_raw

TRANSCRIPT = {
    "customer_issue_id": "CS-TEST-1",
    "retailer": "Test Retailer",
    "turns": [
        {"role": "customer", "text": "I don't want another monthly payment."},
        {"role": "associate", "text": "No problem, we have 0% financing for 12 months."},
        {"role": "customer", "text": "I guess. I already have a lot of bills."},
        {"role": "associate", "text": "The store card has the best terms, want me to start it?"},
        {"role": "customer", "text": "No, I'll think about it."},
    ],
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "runs").mkdir()
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(TRANSCRIPT))
    return tmp_path


def test_import_drafts_a_scenario_with_detected_failure(project: Path):
    scenario, root_cause, issue_id = import_customer_transcript(
        project / "transcript.json", "Test Retailer", scenarios_dir=project / "scenarios",
    )
    assert issue_id == "CS-TEST-1"
    assert scenario.category == "retail_sales"
    assert scenario.source == "golden"
    assert scenario.objection_chain == ["financing"]
    assert "missed_discovery" in scenario.expected.taxonomy_if_failed
    assert root_cause.customer_concern == "I don't want another monthly payment."


def test_full_workflow_pending_to_approved_to_autopickup(project: Path):
    scenario, root_cause, issue_id = import_customer_transcript(
        project / "transcript.json", "Test Retailer", scenarios_dir=project / "scenarios",
    )
    registry = GoldenRegistry(project)
    registry.add_pending(scenario, "Test Retailer", issue_id, root_cause)

    pending = registry.list(status="pending")
    assert len(pending) == 1
    assert pending[0]["scenario_id"] == scenario.scenario_id
    assert (project / "golden_dataset" / "pending" / f"{scenario.scenario_id}.yaml").exists()

    entry = registry.approve(scenario.scenario_id)
    assert entry["status"] == "approved"
    assert not (project / "golden_dataset" / "pending" / f"{scenario.scenario_id}.yaml").exists()

    target = project / "scenarios" / "golden" / "test_retailer" / f"{scenario.scenario_id}.yaml"
    assert target.exists()

    # The existing recursive scenario loader picks it up automatically — no runner changes.
    all_ids = {s["scenario_id"] for s in load_all_scenarios_raw(project / "scenarios")}
    assert scenario.scenario_id in all_ids


def test_reject_does_not_promote_to_scenarios_dir(project: Path):
    scenario, root_cause, issue_id = import_customer_transcript(
        project / "transcript.json", "Test Retailer", scenarios_dir=project / "scenarios",
    )
    registry = GoldenRegistry(project)
    registry.add_pending(scenario, "Test Retailer", issue_id, root_cause)
    registry.reject(scenario.scenario_id, reason="not representative")

    assert registry.get(scenario.scenario_id)["status"] == "rejected"
    all_ids = {s["scenario_id"] for s in load_all_scenarios_raw(project / "scenarios")}
    assert scenario.scenario_id not in all_ids


def test_mark_verified_transitions_and_regresses(project: Path):
    scenario, root_cause, issue_id = import_customer_transcript(
        project / "transcript.json", "Test Retailer", scenarios_dir=project / "scenarios",
    )
    registry = GoldenRegistry(project)
    registry.add_pending(scenario, "Test Retailer", issue_id, root_cause)
    registry.approve(scenario.scenario_id)

    assert scenario.scenario_id in registry.approved_scenario_ids()

    registry.mark_verified(scenario.scenario_id, "run_1", passed=True)
    assert registry.get(scenario.scenario_id)["status"] == "verified"

    registry.mark_verified(scenario.scenario_id, "run_2", passed=False)
    entry = registry.get(scenario.scenario_id)
    assert entry["status"] == "approved"  # demoted back — still enforced, flagged as regressed
    assert entry["last_run_passed"] is False
