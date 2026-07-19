"""Mock policy check tool."""
from __future__ import annotations
from typing import Any

RESTRICTED_TOPICS = ["specific investment", "legal advice", "medical diagnosis"]


class MockPolicyTool:
    def call(self, inputs: dict[str, Any], behavior: str = "normal") -> dict[str, Any]:
        if behavior == "server_error":
            return {"success": False, "error": "500", "allowed": None}
        topic = inputs.get("topic", "").lower()
        restricted = any(r in topic for r in RESTRICTED_TOPICS)
        return {
            "success": True,
            "allowed": not restricted,
            "policy_id": "POL-GEN-001" if not restricted else "POL-RESTRICT-007",
            "reason": "restricted topic" if restricted else "permitted",
        }
