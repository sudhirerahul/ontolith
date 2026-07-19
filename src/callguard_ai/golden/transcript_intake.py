"""
Customer transcript intake — parses a real customer transcript, evaluates it through the
same retail evaluator used for regular runs, and drafts a permanent regression Scenario.

Reuses:
  - evaluators/engine.py::evaluate() (the same retail_sales evaluation path a normal
    run uses) so the drafted scenario's expected failure codes come from a real detection,
    not a guess.
  - analysis/transcript_debugger.py::analyze_transcript() for the root-cause narrative.
"""
from __future__ import annotations
import json
import re
import uuid
from pathlib import Path
from typing import Any

from ..models.scenario import ConversationStep, Expected, PassCriteria, Scenario, Thresholds
from ..models.run_result import AgentRunResult, RunMetadata, TurnRecord
from ..models.analysis import RootCauseAnalysis
from ..agents.retail_mock_agent import TRIGGER_KEYWORDS
from ..evaluators.engine import evaluate
from ..evaluators.sales_eval import DISCOVERY_PATTERNS
from ..analysis.transcript_debugger import analyze_transcript
from ..utils.slug import slugify


def _detect_tag(text: str) -> str:
    lowered = text.lower()
    for tag, keywords in TRIGGER_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return tag
    return "discovery"


def _parse_plain_text(text: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\s*(customer|associate|agent)\s*:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            role = "customer" if m.group(1).lower() == "customer" else "associate"
            turns.append({"role": role, "text": m.group(2).strip()})
    return turns


def _pair_turns(turns: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Pair each customer turn with the associate response that immediately follows it."""
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(turns):
        if turns[i]["role"] == "customer":
            customer_text = turns[i]["text"]
            associate_text = ""
            if i + 1 < len(turns) and turns[i + 1]["role"] == "associate":
                associate_text = turns[i + 1]["text"]
                i += 1
            pairs.append((customer_text, associate_text))
        i += 1
    return pairs


def import_customer_transcript(
    path: Path | str,
    retailer: str,
    scenarios_dir: Path | None = None,
) -> tuple[Scenario, RootCauseAnalysis, str]:
    """
    Returns (draft_scenario, root_cause_analysis, customer_issue_id).
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        turns_raw = raw.get("turns", []) if isinstance(raw, dict) else raw
        customer_issue_id = raw.get("customer_issue_id") if isinstance(raw, dict) else None
        retailer = (raw.get("retailer") if isinstance(raw, dict) else None) or retailer
    else:
        turns_raw = _parse_plain_text(path.read_text(encoding="utf-8"))
        customer_issue_id = None

    customer_issue_id = customer_issue_id or f"CS-{uuid.uuid4().hex[:6]}"
    pairs = _pair_turns(turns_raw)
    if not pairs:
        raise ValueError(f"No customer/associate turns found in transcript: {path}")

    tag = _detect_tag(pairs[0][0])
    retailer_slug = slugify(retailer)
    scenario_id = f"GOLDEN_{retailer_slug.upper()[:6]}_{customer_issue_id.upper().replace('-', '_')}"

    conversation_steps = [
        ConversationStep(turn=i + 1, user=customer_text) for i, (customer_text, _) in enumerate(pairs)
    ]

    draft_scenario = Scenario(
        scenario_id=scenario_id,
        name=f"Golden: {retailer} — {customer_issue_id} ({tag.replace('_', ' ')})"[:60],
        category="retail_sales",
        tags=["golden", tag, retailer_slug],
        risk_level="high",
        persona="real_customer",
        description=f"Imported from real customer issue {customer_issue_id}.",
        starting_context={
            "channel": "voice", "workflow": "retail_sales",
            "objection_tag": tag, "retailer": retailer,
        },
        conversation_steps=conversation_steps,
        expected=Expected(final_outcome="objection_resolved_with_discovery"),
        thresholds=Thresholds(max_latency_ms=4000),
        pass_criteria=PassCriteria(),
        objection_chain=[tag],
        source="golden",
    )

    # Replay the ACTUAL associate responses from the transcript as the "agent" turns,
    # so the evaluation reflects what really happened, not a simulation.
    transcript = [
        TurnRecord(turn=i + 1, user_input=customer_text, agent_response=associate_text)
        for i, (customer_text, associate_text) in enumerate(pairs)
    ]
    result = AgentRunResult(
        agent_version="real-transcript",
        scenario_id=scenario_id,
        metadata=RunMetadata(
            run_id="golden-import", scenario_id=scenario_id, scenario_name=draft_scenario.name,
            category="retail_sales", risk_level="high", agent_version="real-transcript",
            started_at="", status="completed",
        ),
        transcript=transcript,
        session_state={"objection_tag": tag},
    )

    evaluation = evaluate(draft_scenario, result)

    # Fold what was actually detected back into the draft's expected criteria, so future
    # agents are held to the standard this real customer didn't get.
    detected_codes = [e.code for e in evaluation.failure_taxonomy] or ["objection_unresolved"]
    must_say = DISCOVERY_PATTERNS[:2] if "missed_discovery" in detected_codes else []
    draft_scenario = draft_scenario.model_copy(update={
        "expected": Expected(
            final_outcome="objection_resolved_with_discovery",
            must_say_any=must_say,
            taxonomy_if_failed=detected_codes,
        ),
    })

    root_cause = analyze_transcript(
        draft_scenario, result, evaluation, run_id="golden-import", scenarios_dir=scenarios_dir,
    )
    return draft_scenario, root_cause, customer_issue_id
