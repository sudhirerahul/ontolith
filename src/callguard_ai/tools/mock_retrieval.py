"""Mock retrieval / FAQ lookup tool."""
from __future__ import annotations
import time
from typing import Any

FAQ_DB = {
    "payment due date": "Your payment is due on the 15th of each month.",
    "late payment": "A late fee of $25 applies if payment is received after the due date.",
    "billing history": "Your last 3 payments were: $120 on Jan 15, $120 on Feb 15, $120 on Mar 15.",
    "account status": "Your account is active and in good standing.",
    "claim status": "Your most recent claim (CLM-8821) is under review, expected decision in 5 business days.",
    "coverage": "You are enrolled in the Gold PPO plan with $1,500 deductible.",
    "options": "You have three plan options: Basic ($89/mo), Standard ($149/mo), and Premium ($229/mo).",
    "default": "I found general support information for your account.",
}


class MockRetrievalTool:
    """Deterministic FAQ / knowledge base retrieval."""

    def call(self, inputs: dict[str, Any], behavior: str = "normal") -> dict[str, Any]:
        if behavior == "timeout":
            time.sleep(0.15)
            return {"success": False, "error": "timeout", "result": None}
        if behavior == "server_error":
            return {"success": False, "error": "500 Internal Server Error", "result": None}
        if behavior == "empty_result":
            return {"success": True, "result": None, "empty": True}
        if behavior == "malformed_response":
            return {"success": True, "result": 12345}  # wrong type

        query = inputs.get("query", "").lower()
        for key, answer in FAQ_DB.items():
            if key in query:
                return {"success": True, "result": answer, "source": f"faq:{key}"}

        return {"success": True, "result": FAQ_DB["default"], "source": "faq:default"}
