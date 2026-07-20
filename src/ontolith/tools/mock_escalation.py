"""Mock escalation tool."""
from __future__ import annotations
from typing import Any


class MockEscalationTool:
    def call(self, inputs: dict[str, Any], behavior: str = "normal") -> dict[str, Any]:
        if behavior == "timeout":
            return {"success": False, "error": "timeout", "escalated": False}
        reason = inputs.get("reason", "unknown")
        priority = inputs.get("priority", "normal")
        return {
            "success": True,
            "escalated": True,
            "ticket_id": f"ESC-{abs(hash(reason)) % 9999:04d}",
            "queue": "crisis" if priority == "critical" else "general",
            "estimated_wait_seconds": 30 if priority == "critical" else 180,
        }
