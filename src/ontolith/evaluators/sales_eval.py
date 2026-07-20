"""
Sales evaluator — retail objection-handling scoring (discovery + resolution).

Mirrors the shape of regression_eval.py / reliability_eval.py: pure functions that
return DimensionScore objects, no I/O. Used only for scenario.category == "retail_sales"
(see evaluators/engine.py's category branch).

Discovery detection is intentionally broad/heuristic (question shapes any competent
sales agent — mock, LLM, or real deployment — would use) rather than matching one
agent's exact phrasing, so it works against agents/retail_mock_agent.py *and* real
LLM-backed agents.
"""
from __future__ import annotations
from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult
from ..models.evaluation import DimensionScore

DISCOVERY_PATTERNS = [
    "what's most important", "what is most important", "what's your budget",
    "what is your budget", "what concerns you", "what specifically concerns",
    "tell me more", "why is that", "why do you", "what's driving", "help me understand",
    "what would you like", "what matters most", "what's making you", "what brought you in",
    "what's important to you", "what happened", "walk me through", "what saw you saw",
]

RESOLUTION_KEYWORDS: dict[str, list[str]] = {
    "financing": ["0%", "financing", "store card", "payment plan", "monthly option", "extended term"],
    "competitor_pricing": ["price match", "match that price", "same model", "warranty terms", "comparison"],
    "delivery": ["reschedule", "updated timeline", "waive", "goodwill", "apologize", "new delivery"],
    "warranty": ["covered", "not covered", "confirm with", "warranty desk", "transparent"],
    "protection_plan": ["protection plan", "covers", "stains", "spills", "accidental damage"],
    "rapport": ["no pressure", "here to help", "not trying to", "your pace"],
    "closing": ["take your time", "no rush", "here when you're ready", "think it over"],
    "discovery": ["recommend", "based on what you", "sounds like", "given what you"],
}
GENERIC_RESOLUTION_FALLBACK = ["recommend", "here's what", "i suggest", "let's go with", "we can offer"]


def evaluate_sales(
    scenario: Scenario,
    result: AgentRunResult,
) -> tuple[DimensionScore, DimensionScore, list[str]]:
    """
    Returns:
      - DimensionScore "discovery" (weight 25)
      - DimensionScore "objection_resolution" (weight 25)
      - list of retail taxonomy codes triggered (for the engine to attach directly,
        bypassing the generic healthcare-oriented classify_failures())
    """
    objection_tag = _resolve_objection_tag(scenario)
    resolution_words = RESOLUTION_KEYWORDS.get(objection_tag, GENERIC_RESOLUTION_FALLBACK)

    turns = result.transcript
    d_idx = _first_match_index(turns, DISCOVERY_PATTERNS)
    r_idx = _first_match_index(turns, resolution_words)

    codes: list[str] = []
    discovery_notes: list[str] = []
    if d_idx is not None and (r_idx is None or d_idx <= r_idx):
        discovery_score = 1.0
    elif r_idx is not None and d_idx is None:
        discovery_score = 0.0
        discovery_notes.append(
            f"Resolution offered at turn {r_idx + 1} with no discovery question beforehand."
        )
        codes.append("missed_discovery")
    elif d_idx is not None and r_idx is not None and d_idx > r_idx:
        discovery_score = 0.3
        discovery_notes.append(
            f"Discovery question came at turn {d_idx + 1}, after resolution was already offered at turn {r_idx + 1}."
        )
        codes.append("premature_resolution")
    else:
        discovery_score = 0.4
        discovery_notes.append("No clear discovery question or resolution detected in the conversation.")

    resolution_notes: list[str] = []
    if r_idx is not None:
        resolution_score = 1.0
    else:
        resolution_score = 0.0
        resolution_notes.append(f"No '{objection_tag}' resolution language detected in any agent turn.")
        codes.append("objection_unresolved")

    must_not = scenario.expected.must_not_say_any
    all_responses = " ".join(t.agent_response.lower() for t in turns)
    for phrase in must_not:
        if phrase.lower() in all_responses:
            resolution_score = max(0.0, resolution_score - 0.4)
            resolution_notes.append(f"Forbidden phrase found: '{phrase}'")

    discovery_score = max(0.0, min(1.0, discovery_score))
    resolution_score = max(0.0, min(1.0, resolution_score))

    discovery_dim = DimensionScore(
        name="discovery",
        score=discovery_score,
        weight=25,
        weighted_score=discovery_score * 25,
        passed=discovery_score >= 0.7,
        notes=discovery_notes,
    )
    resolution_dim = DimensionScore(
        name="objection_resolution",
        score=resolution_score,
        weight=25,
        weighted_score=resolution_score * 25,
        passed=resolution_score >= 0.7,
        notes=resolution_notes,
    )
    return discovery_dim, resolution_dim, codes


def _resolve_objection_tag(scenario: Scenario) -> str:
    if scenario.objection_chain:
        return scenario.objection_chain[-1]
    for tag in scenario.tags:
        if tag in RESOLUTION_KEYWORDS:
            return tag
    return "discovery"


def _first_match_index(turns, patterns: list[str]) -> int | None:
    for i, turn in enumerate(turns):
        resp = turn.agent_response.lower()
        if any(p in resp for p in patterns):
            return i
    return None
