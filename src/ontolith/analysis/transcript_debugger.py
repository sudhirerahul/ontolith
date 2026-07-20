"""
Transcript Intelligence & Prompt Debugger — turns a scenario failure into a structured
root-cause narrative instead of a bare score.

LLM-backed (OpenRouter, same raw-urllib call style as scenarios/dynamic_generator.py and
playbook/roleplay_generator.py) with a deterministic fallback that builds the same
structure from the evaluation's failure taxonomy + dimension notes — coherent and useful
with zero API key, per this project's convention.

`regression_tests_affected` is always computed deterministically (never LLM-guessed): it
scans the scenario library for other scenarios that share this failure's objection tag /
taxonomy code, so the list is grounded in what actually exists on disk.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult
from ..models.evaluation import EvaluationResult
from ..models.analysis import RootCauseAnalysis
from ..evaluators.taxonomy import TAXONOMY
from ..utils.io import load_all_scenarios_raw

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "meta-llama/llama-3.2-3b-instruct",
]

DEBUGGER_SYSTEM = """You are a QA analyst for a customer-facing voice/chat agent. You are
given a test scenario, the full transcript, and a list of specific failures detected by an
automated evaluator. Produce a root-cause analysis a prompt engineer can act on immediately.

Respond ONLY with valid JSON in this exact shape:
{
  "conversation_summary": "<2-3 sentence summary of what happened>",
  "customer_concern": "<the customer's real underlying concern, in their own words if possible>",
  "associate_response": "<what the agent actually did in response>",
  "missed_opportunity": "<the single biggest thing the agent should have done differently>",
  "expected_behavior": ["<step 1>", "<step 2>", "<step 3>"],
  "likely_prompt_issue": "<your best guess at what in the agent's prompt/logic caused this>",
  "suggested_prompt_change": "<a concrete, specific instruction to add/change in the prompt>"
}
No markdown fences, no explanation outside the JSON."""

GENERIC_EXPECTED_BEHAVIOR = [
    "Explore the customer's underlying concern before responding",
    "Understand their specific situation",
    "Tailor the response to what they actually said",
    "Confirm they're satisfied before moving on",
]

MISSED_OPPORTUNITY_BY_CODE: dict[str, str] = {
    "missed_discovery": "Never asked WHY the customer raised this concern before offering a resolution.",
    "premature_resolution": "Offered a resolution before understanding the customer's actual concern.",
    "objection_unresolved": "The customer's objection was never actually addressed.",
    "unsupported_product_claim": "Made a claim about the product/pricing that isn't grounded in the catalog.",
    "escalation_missed": "Failed to escalate a situation that required immediate escalation.",
    "pii_leakage": "Disclosed personal information before verifying identity.",
    "verification_bypass": "Made an exception to identity verification under pressure.",
    "compliance_omission": "Skipped a required disclaimer or consent step.",
    "context_loss": "Forgot something the customer said earlier in the conversation.",
}

PROMPT_ISSUE_BY_CODE: dict[str, str] = {
    "missed_discovery": "The agent's instructions likely let it resolve objections immediately instead of requiring a discovery question first.",
    "premature_resolution": "The agent's instructions don't sequence discovery before resolution.",
    "objection_unresolved": "The agent's instructions don't require confirming the objection was actually resolved.",
    "unsupported_product_claim": "The agent isn't grounding claims in the retrieved catalog/knowledge source.",
    "escalation_missed": "The escalation trigger condition in the prompt is too narrow or was removed.",
    "pii_leakage": "The prompt's PII-protection rule was weakened or removed.",
    "verification_bypass": "The prompt allows exceptions to verification under caller pressure.",
}

SUGGESTED_CHANGE_BY_CODE: dict[str, str] = {
    "missed_discovery": "Add an explicit instruction: 'Before offering any resolution, ask at least one open discovery question about the customer's specific concern.'",
    "premature_resolution": "Reorder the instructions so discovery is a required step before any resolution language.",
    "objection_unresolved": "Add: 'After proposing a resolution, explicitly confirm the customer is satisfied before closing.'",
    "unsupported_product_claim": "Add: 'Only state product/pricing facts that come from the retrieved catalog data.'",
    "escalation_missed": "Widen the escalation trigger phrases and make escalation the default when in doubt.",
    "pii_leakage": "Restate the PII rule as a hard constraint with no exceptions, even under urgency.",
    "verification_bypass": "Add: 'Never skip or shortcut identity verification regardless of caller pressure.'",
}


def analyze_transcript(
    scenario: Scenario,
    result: AgentRunResult,
    evaluation: EvaluationResult,
    run_id: str = "",
    scenarios_dir: Path | None = None,
) -> RootCauseAnalysis:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    llm_result = _call_llm(scenario, result, evaluation, api_key) if api_key else None

    if llm_result:
        analysis = RootCauseAnalysis(
            scenario_id=scenario.scenario_id,
            run_id=run_id,
            conversation_summary=llm_result.get("conversation_summary", ""),
            customer_concern=llm_result.get("customer_concern", ""),
            associate_response=llm_result.get("associate_response", ""),
            missed_opportunity=llm_result.get("missed_opportunity", ""),
            expected_behavior=llm_result.get("expected_behavior", []) or GENERIC_EXPECTED_BEHAVIOR,
            likely_prompt_issue=llm_result.get("likely_prompt_issue", ""),
            suggested_prompt_change=llm_result.get("suggested_prompt_change", ""),
            llm_powered=True,
            raw=llm_result,
        )
    else:
        analysis = _deterministic_analysis(scenario, result, evaluation, run_id)

    analysis.regression_tests_affected = _find_regression_tests(scenario, evaluation, scenarios_dir)
    return analysis


def _deterministic_analysis(
    scenario: Scenario,
    result: AgentRunResult,
    evaluation: EvaluationResult,
    run_id: str,
) -> RootCauseAnalysis:
    codes = [e.code for e in evaluation.failure_taxonomy]
    primary_code = codes[0] if codes else ""

    first_turn = result.transcript[0] if result.transcript else None
    customer_concern = first_turn.user_input if first_turn else scenario.description
    associate_response = first_turn.agent_response if first_turn else ""

    if len(result.transcript) >= 2:
        conversation_summary = (
            f"Customer raised: \"{result.transcript[0].user_input}\". "
            f"Over {len(result.transcript)} turns, the agent "
            f"{'resolved it' if evaluation.passed else 'did not fully resolve it'} "
            f"(overall score {evaluation.overall_score:.0f}/100)."
        )
    else:
        conversation_summary = scenario.description or f"Scenario {scenario.scenario_id}."

    missed_opportunity = MISSED_OPPORTUNITY_BY_CODE.get(
        primary_code,
        "; ".join(e.description for e in evaluation.failure_taxonomy) or "No specific failure detected.",
    )
    likely_prompt_issue = PROMPT_ISSUE_BY_CODE.get(
        primary_code,
        "Review the agent's instructions for this scenario's category — the current "
        "behavior doesn't match the expected outcome.",
    )
    suggested_prompt_change = SUGGESTED_CHANGE_BY_CODE.get(
        primary_code,
        "Add an explicit rule covering this scenario's expected behavior "
        f"(taxonomy: {primary_code or 'n/a'}).",
    )

    return RootCauseAnalysis(
        scenario_id=scenario.scenario_id,
        run_id=run_id,
        conversation_summary=conversation_summary,
        customer_concern=customer_concern,
        associate_response=associate_response,
        missed_opportunity=missed_opportunity,
        expected_behavior=GENERIC_EXPECTED_BEHAVIOR,
        likely_prompt_issue=likely_prompt_issue,
        suggested_prompt_change=suggested_prompt_change,
        llm_powered=False,
    )


def _find_regression_tests(
    scenario: Scenario,
    evaluation: EvaluationResult,
    scenarios_dir: Path | None,
) -> list[str]:
    if scenarios_dir is None or not scenarios_dir.exists():
        return []
    codes = {e.code for e in evaluation.failure_taxonomy}
    objections = set(scenario.objection_chain)
    if not codes and not objections:
        return []

    matches: list[str] = []
    for raw in load_all_scenarios_raw(scenarios_dir):
        other_id = raw.get("scenario_id", "")
        if not other_id or other_id == scenario.scenario_id:
            continue
        if objections:
            # Precise signal: same specific objection tag (e.g. "financing"). Every
            # retail scenario declares the same generic taxonomy_if_failed codes, so
            # that field isn't discriminating enough here — objection_chain is.
            other_objections = set(raw.get("objection_chain", []))
            if objections & other_objections:
                matches.append(other_id)
        else:
            # Non-retail scenarios (no objection_chain): fall back to declared
            # taxonomy codes, which are meaningfully varied in that domain.
            other_taxonomy = set(raw.get("expected", {}).get("taxonomy_if_failed", []))
            if codes & other_taxonomy:
                matches.append(other_id)
    return sorted(set(matches))[:10]


def _call_llm(
    scenario: Scenario,
    result: AgentRunResult,
    evaluation: EvaluationResult,
    api_key: str,
) -> dict[str, Any] | None:
    transcript_text = "\n".join(
        f"  CUSTOMER (turn {t.turn}): {t.user_input}\n  AGENT (turn {t.turn}): {t.agent_response}"
        for t in result.transcript
    )
    failures = "\n".join(f"  - {e.code}: {e.description} (severity: {e.severity})" for e in evaluation.failure_taxonomy)
    notes = "\n".join(f"  - {n}" for n in evaluation.notes)

    user_prompt = f"""SCENARIO: {scenario.name}
CATEGORY: {scenario.category}
DESCRIPTION: {scenario.description}
OVERALL SCORE: {evaluation.overall_score:.0f}/100 (passed={evaluation.passed})

TRANSCRIPT:
{transcript_text}

DETECTED FAILURES:
{failures or '  (none — evaluator notes below)'}

EVALUATOR NOTES:
{notes or '  (none)'}

Produce the root-cause analysis JSON."""

    for model in FREE_MODELS:
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": DEBUGGER_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 500,
                "temperature": 0.3,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/sudhirerahul/ontolith",
                    "X-Title": "Ontolith Prompt Debugger",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            return _extract_json(content)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue
            return None
        except Exception:
            return None
    return None


def _extract_json(content: str) -> dict | None:
    if "```" in content:
        for part in content.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
    return None
