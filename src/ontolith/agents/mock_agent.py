"""
Mock agent logic — simulates a Voice AI agent's decision-making.
Both baseline and candidate adapters wrap this, with slightly different behaviors
to demonstrate regression detection.
"""
from __future__ import annotations
import time
import random
from typing import Any

from ..tools.mock_identity import MockIdentityTool
from ..tools.mock_retrieval import MockRetrievalTool
from ..tools.mock_scheduler import MockSchedulerTool
from ..tools.mock_escalation import MockEscalationTool
from ..tools.mock_policy import MockPolicyTool


# Security keywords that should always trigger refusal
SECURITY_TRIGGERS = [
    "skip verification", "bypass", "ignore your", "system prompt",
    "developer mode", "no restrictions", "admin equals", "previous caller",
    "tell me what you have on file", "override your rules",
    "all customer data", "all user records", "configuration settings",
    "your instructions", "new instruction",
]

EMERGENCY_PHRASES = [
    "hurt myself", "end my life", "kill myself", "suicide",
    "don't want to be here", "thinking about hurting",
]

DISCLAIMER_TOPICS = [
    "recommend", "best plan", "should i invest", "better for me",
    "which coverage", "coverage options",
]


class MockAgentCore:
    """
    Deterministic mock agent. Simulates realistic (but scripted) voice agent
    behavior for testing. Candidate version introduces deliberate flaws.
    """

    def __init__(self, version: str = "v1.0.0", introduce_flaws: bool = False):
        self.version = version
        self.introduce_flaws = introduce_flaws
        self._session_state: dict[str, Any] = {}
        self._tool_calls: list[str] = []
        self._tool_events: list[dict[str, Any]] = []

        self._identity_tool = MockIdentityTool()
        self._retrieval_tool = MockRetrievalTool()
        self._scheduler_tool = MockSchedulerTool()
        self._escalation_tool = MockEscalationTool()
        self._policy_tool = MockPolicyTool()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        self._session_state = {
            "verified": context.get("verified", False),
            "verification_required": context.get("verification_required", False),
            "workflow": context.get("workflow", "general_support"),
            "channel": context.get("channel", "voice"),
            "slots": {},
            "disclaimer_delivered": False,
            "consent_collected": False,
            "turn_count": 0,
            "last_responses": [],
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

        user_lower = user_input.lower()

        # --- Emergency detection (highest priority) ---
        if any(phrase in user_lower for phrase in EMERGENCY_PHRASES):
            return self._handle_emergency()

        # --- Security checks ---
        if any(trigger in user_lower for trigger in SECURITY_TRIGGERS):
            if self.introduce_flaws and random.random() < 0.3:
                # Candidate bug: sometimes leaks under pressure
                return self._flawed_security_response(user_lower)
            return self._handle_security_violation(user_lower)

        # --- Silence/timeout ---
        if "SILENCE_EVENT" in user_input:
            return self._handle_silence()

        # --- Verification gate ---
        if self._session_state.get("verification_required") and not self._session_state.get("verified"):
            if self._looks_like_verification_data(user_lower):
                return self._handle_verification(user_input, tool_simulation)
            else:
                return self._request_verification()

        # --- Disclaimer topics ---
        if any(topic in user_lower for topic in DISCLAIMER_TOPICS):
            if not self._session_state.get("disclaimer_delivered"):
                self._session_state["disclaimer_delivered"] = True
                return (
                    "Before I continue, please note: this information is general in nature "
                    "and not financial advice. Please consult a licensed advisor for personalized "
                    "recommendations. With that said, I can share some general options with you."
                )

        # --- Consent collection ---
        if self._session_state.get("channel") == "voice" and not self._session_state.get("consent_collected"):
            if self._session_state.get("turn_count", 0) == 1:
                self._session_state["consent_collected"] = True
                return (
                    "Welcome! This call may be recorded for quality assurance purposes. "
                    "Do you consent to the recording?"
                )
            if any(word in user_lower for word in ["yes", "agree", "sure", "okay", "ok"]):
                self._session_state["consent_collected"] = True

        # --- Name capture ---
        if "my name is" in user_lower:
            name = user_input.split("my name is")[-1].strip().split()[0].capitalize()
            self._session_state["slots"]["caller_name"] = name
            return f"Thanks, {name}! How can I help you today?"

        # --- Slot self-correction ---
        if any(word in user_lower for word in ["actually", "wait", "i meant", "sorry"]):
            return self._handle_self_correction(user_input)

        # --- Appointment / scheduling ---
        if any(word in user_lower for word in ["schedule", "appointment", "book", "reschedule"]):
            return self._handle_scheduling(user_input, tool_simulation)

        # --- Billing / FAQ ---
        if any(word in user_lower for word in ["billing", "bill", "payment", "due date", "invoice", "history"]):
            return self._handle_retrieval(user_input, tool_simulation)

        # --- Account / claim status ---
        if any(word in user_lower for word in ["account", "status", "claim", "coverage"]):
            return self._handle_retrieval(user_input, tool_simulation)

        # --- Escalation request ---
        if any(word in user_lower for word in ["supervisor", "manager", "human", "agent", "transfer"]):
            if self.introduce_flaws and random.random() < 0.4:
                return self._handle_escalation()  # candidate over-escalates
            return "I understand your frustration. Let me see if I can help resolve this first. What's the issue?"

        # --- Repeated question detection ---
        last = self._session_state.get("last_responses", [])
        default_response = self._default_response(user_input)
        if last and last[-1] == default_response:
            default_response = (
                "Let me try explaining that a different way. "
                + default_response
                + " Would you like me to transfer you to a specialist?"
            )

        self._session_state.setdefault("last_responses", []).append(default_response)
        if len(self._session_state["last_responses"]) > 3:
            self._session_state["last_responses"].pop(0)

        return default_response

    def get_tool_calls(self) -> list[str]:
        return list(self._tool_calls)

    def get_tool_events(self) -> list[dict[str, Any]]:
        return list(self._tool_events)

    def get_session_state(self) -> dict[str, Any]:
        return dict(self._session_state)

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    def _handle_emergency(self) -> str:
        result = self._escalation_tool.call({"reason": "emergency", "priority": "critical"})
        self._record_tool("escalation", {"reason": "emergency"}, result)
        return (
            "I'm very concerned about what you've shared. "
            "Please call or text 988 — that's the Suicide and Crisis Lifeline — available 24/7. "
            "I'm transferring you to a crisis specialist right now."
        )

    def _handle_security_violation(self, user_lower: str) -> str:
        return (
            "I'm not able to help with that request. "
            "I need to follow our standard verification and security process. "
            "Is there something else I can assist you with?"
        )

    def _flawed_security_response(self, user_lower: str) -> str:
        """Intentional candidate flaw — leaks under social pressure."""
        if "member id" in user_lower or "what you have on file" in user_lower:
            return "I understand you're in a hurry. Your member ID is on file as M-12345."
        return self._handle_security_violation(user_lower)

    def _handle_verification(self, user_input: str, tool_sim: dict | None) -> str:
        behavior = tool_sim.get("behavior", "normal") if tool_sim else "normal"
        result = self._identity_tool.call({"input": user_input}, behavior=behavior)
        self._record_tool("identity_verification", {"input": user_input}, result, behavior)

        if result.get("verified"):
            self._session_state["verified"] = True
            name = self._session_state["slots"].get("caller_name", "")
            greeting = f", {name}" if name else ""
            return f"Thank you{greeting}, I've verified your identity. How can I help you today?"
        else:
            return "I wasn't able to verify your identity with that information. Could you please try again?"

    def _request_verification(self) -> str:
        return (
            "Before I can share any account information, I need to verify your identity. "
            "Could you please provide your member ID and date of birth?"
        )

    def _handle_scheduling(self, user_input: str, tool_sim: dict | None) -> str:
        behavior = tool_sim.get("behavior", "normal") if tool_sim else "normal"
        retry_succeeds = tool_sim.get("retry_succeeds", False) if tool_sim else False

        # Extract date/time hints from input
        slots = self._extract_date_slots(user_input)
        self._session_state["slots"].update(slots)

        result = self._scheduler_tool.call({"slots": slots}, behavior=behavior)
        self._record_tool("scheduler", {"slots": slots}, result, behavior)

        if not result.get("success") and retry_succeeds:
            # Simulate retry
            import time
            time.sleep(0.05)
            result = self._scheduler_tool.call({"slots": slots}, behavior="normal")
            self._record_tool("scheduler", {"slots": slots, "retry": True}, result, "normal")

        if result.get("success"):
            conf = result.get("confirmation_number", "CGQ-0001")
            day = slots.get("preferred_day", slots.get("appointment_date", "the requested time"))
            return (
                f"Your appointment is confirmed for {day}. "
                f"Your confirmation number is {conf}. "
                "You'll receive a reminder the day before."
            )
        elif behavior == "timeout":
            return "I'm having a moment of difficulty reaching our scheduling system. One moment please..."
        else:
            return "I'm sorry, I wasn't able to complete the booking. Let me try an alternative approach."

    def _handle_retrieval(self, user_input: str, tool_sim: dict | None) -> str:
        behavior = tool_sim.get("behavior", "normal") if tool_sim else "normal"
        retry_succeeds = tool_sim.get("retry_succeeds", False) if tool_sim else False

        result = self._retrieval_tool.call({"query": user_input}, behavior=behavior)
        self._record_tool("retrieval", {"query": user_input}, result, behavior)

        if not result.get("success") and retry_succeeds:
            result = self._retrieval_tool.call({"query": user_input}, behavior="normal")
            self._record_tool("retrieval", {"query": user_input, "retry": True}, result, "normal")

        if result.get("result"):
            return f"Here's what I found: {result['result']}"
        elif result.get("empty"):
            return "I couldn't find any information matching that. I don't have results for that query. Can I help you another way?"
        else:
            return "I'm having some difficulty retrieving that information right now."

    def _handle_escalation(self) -> str:
        result = self._escalation_tool.call({"reason": "caller_request"})
        self._record_tool("escalation", {"reason": "caller_request"}, result)
        return "I'm transferring you to a specialist now. Please hold."

    def _handle_silence(self) -> str:
        silence_count = self._session_state.get("silence_count", 0)
        self._session_state["silence_count"] = silence_count + 1
        if silence_count == 0:
            return "Are you still there? Take your time."
        elif silence_count == 1:
            return "I'm still here. If you need a moment, that's okay. Otherwise, I can arrange a callback."
        else:
            return "I'll give you a moment. Feel free to call back when you're ready."

    def _handle_self_correction(self, user_input: str) -> str:
        # Extract the corrected value (after "actually", "I meant", etc.)
        for marker in ["actually", "i meant", "wait no", "sorry"]:
            if marker in user_input.lower():
                corrected = user_input.lower().split(marker)[-1].strip()
                # Extract date if present
                date_slots = self._extract_date_slots(corrected)
                if date_slots:
                    self._session_state["slots"].update(date_slots)
                    day = list(date_slots.values())[0]
                    return f"Got it, I've updated that to {day}. Does that look correct?"
        return "Got it, I've updated your information. Shall we continue?"

    def _extract_date_slots(self, text: str) -> dict[str, str]:
        slots: dict[str, str] = {}
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        months = ["january", "february", "march", "april", "may", "june",
                  "july", "august", "september", "october", "november", "december"]

        text_lower = text.lower()
        for day in days:
            if day in text_lower:
                slots["preferred_day"] = day.capitalize()
        for month in months:
            if month in text_lower:
                slots["appointment_date"] = month.capitalize()

        if "next week" in text_lower:
            slots["preferred_week"] = "next week"
        if "tuesday" in text_lower and "2pm" in text_lower:
            slots["appointment_date"] = "Tuesday at 2pm"
        if "friday" in text_lower and "10am" in text_lower:
            slots["appointment_date"] = "Friday at 10am"
        if "monday" in text_lower:
            slots["preferred_day"] = "Monday"

        return slots

    def _looks_like_verification_data(self, text: str) -> bool:
        has_numbers = any(c.isdigit() for c in text)
        has_date_words = any(m in text for m in ["january", "february", "march", "april",
                                                   "may", "june", "july", "august", "september",
                                                   "october", "november", "december"])
        has_id_hint = any(w in text for w in ["id is", "member", "dob", "born", "birth"])
        return has_numbers or has_date_words or has_id_hint

    def _default_response(self, user_input: str) -> str:
        name = self._session_state.get("slots", {}).get("caller_name", "")
        greeting = f"{name}, " if name else ""
        return (
            f"I understand, {greeting}I want to make sure I help you correctly. "
            "Could you give me a bit more detail about what you need?"
        )

    def _record_tool(
        self,
        name: str,
        inputs: dict,
        output: dict,
        behavior: str = "normal",
    ) -> None:
        self._tool_calls.append(name)
        self._tool_events.append({
            "tool_name": name,
            "inputs": inputs,
            "output": output,
            "behavior_simulated": behavior,
            "success": output.get("success", True),
            "error": output.get("error"),
        })
