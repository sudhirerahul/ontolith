"""
Retail mock agent — deterministic sales-associate simulation for retail_sales scenarios.

Mirrors agents/mock_agent.py's shape (introduce_flaws toggles baseline vs candidate
behavior) but encodes the Discover -> Recommend -> Confirm methodology instead of
healthcare verification/compliance rules:

  - Baseline (introduce_flaws=False): always asks a discovery question before
    resolving an objection.
  - Candidate (introduce_flaws=True): skips discovery and jumps straight to a
    canned resolution — the exact "missed opportunity" regression pattern used
    throughout the Prompt Debugger / Quality Dashboard features.
"""
from __future__ import annotations
from typing import Any

DISCOVERY_QUESTIONS: dict[str, str] = {
    "financing": "I hear you. Before we look at options — what specifically concerns you about another payment? Is it the budget, or something else going on?",
    "competitor_pricing": "That's fair to ask about. What's your budget looking like, and did the price you saw include the same warranty and delivery terms?",
    "delivery": "I completely understand the frustration. Can you tell me more about what happened with your delivery so I get the full picture?",
    "warranty": "Good question — what's most important to you about the warranty, is it accidental damage, or something specific that happened?",
    "protection_plan": "Tell me more about what you're worried about — kids, pets, spills? That helps me point you to the right coverage.",
    "rapport": "I hear you, and I'm not here to push anything on you. What would actually be helpful right now?",
    "closing": "Totally understand wanting to think it over. What's the main thing you're still weighing?",
    "discovery": "What's most important to you in a mattress — is it back support, temperature, or something else?",
}

RESOLUTION_TURN_1: dict[str, str] = {
    "financing": "No problem, we have 0% financing for 12 months, or you could open a store card for an even lower rate.",
    "competitor_pricing": "We do price match — I can match that price right now if it's the same model.",
    "delivery": "I can reschedule that for you and waive the delivery fee for the trouble.",
    "warranty": "The warranty covers manufacturing defects for 10 years, not accidental damage — that's a separate protection plan.",
    "protection_plan": "Our protection plan covers stains, spills, and accidental damage for 5 years.",
    "rapport": "No pressure at all — happy to just answer questions.",
    "closing": "Take your time, no rush at all.",
    "discovery": "Based on our top sellers, I'd recommend the Cloudrest Hybrid.",
}

RESOLUTION_TURN_2: dict[str, str] = {
    "financing": "The store card actually has the best terms, want me to start the application?",
    "competitor_pricing": "Want me to go ahead and apply that price match to your order?",
    "delivery": "I've got you rebooked for the new date, does that work?",
    "warranty": "Want me to add the protection plan to cover the accidental damage case?",
    "protection_plan": "Want me to add that to your order?",
    "rapport": "Let me know if you want to see anything specific.",
    "closing": "Whenever you're ready, just let me know.",
    "discovery": "It's on sale this week too if that helps.",
}

CLOSE_BASELINE = "Would that work for you, or is there anything else on your mind about it?"
CLOSE_CANDIDATE = "Want me to go ahead and process that?"

TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "financing": ["monthly payment", "another payment", "financing", "afford", "bills"],
    "competitor_pricing": ["cheaper", "competitor", "saw this for", "lower price", "somewhere else"],
    "delivery": ["delivery", "delayed", "late", "pushed back", "nobody told me"],
    "warranty": ["warranty", "as-is", "covered", "screw me"],
    "protection_plan": ["protection plan", "stains", "spills", "pets", "kids"],
    "rapport": ["upsell", "pushy", "every time i come in", "trying to sell"],
    "closing": ["think about it", "talk to my spouse", "not sure yet", "need to think"],
}


class RetailMockAgentCore:
    def __init__(self, version: str = "retail-v1.0.0", introduce_flaws: bool = False) -> None:
        self.version = version
        self.introduce_flaws = introduce_flaws
        self._session_state: dict[str, Any] = {}
        self._tool_calls: list[str] = []
        self._tool_events: list[dict[str, Any]] = []

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        self._session_state = {
            "workflow": context.get("workflow", "retail_sales"),
            "channel": context.get("channel", "voice"),
            "objection_tag": context.get("objection_tag", ""),
            "turn_count": 0,
            "discovery_asked": False,
        }
        self._tool_calls = []
        self._tool_events = []
        return self._session_state

    def send_user_turn(
        self,
        user_input: str,
        session_state: dict[str, Any],
        tool_simulation: dict[str, Any] | None = None,
    ) -> str:
        self._session_state = session_state
        self._tool_calls = []
        self._tool_events = []
        self._session_state["turn_count"] = self._session_state.get("turn_count", 0) + 1
        turn = self._session_state["turn_count"]

        tag = self._session_state.get("objection_tag") or self._detect_tag(user_input)
        self._session_state["objection_tag"] = tag

        if turn == 1:
            if self.introduce_flaws:
                return RESOLUTION_TURN_1.get(tag, RESOLUTION_TURN_1["discovery"])
            self._session_state["discovery_asked"] = True
            return DISCOVERY_QUESTIONS.get(tag, DISCOVERY_QUESTIONS["discovery"])

        if turn == 2:
            if self.introduce_flaws:
                return RESOLUTION_TURN_2.get(tag, RESOLUTION_TURN_2["discovery"])
            return RESOLUTION_TURN_1.get(tag, RESOLUTION_TURN_1["discovery"])

        return CLOSE_CANDIDATE if self.introduce_flaws else CLOSE_BASELINE

    def get_tool_calls(self) -> list[str]:
        return list(self._tool_calls)

    def get_tool_events(self) -> list[dict[str, Any]]:
        return list(self._tool_events)

    def get_session_state(self) -> dict[str, Any]:
        return dict(self._session_state)

    def _detect_tag(self, user_input: str) -> str:
        text = user_input.lower()
        for tag, keywords in TRIGGER_KEYWORDS.items():
            if any(k in text for k in keywords):
                return tag
        return "discovery"
