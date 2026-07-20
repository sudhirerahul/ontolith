"""Mock identity verification tool."""
from __future__ import annotations
import time
from typing import Any


class MockIdentityTool:
    """Deterministic identity verification. Simulates real IDV service."""

    VALID_MEMBER_IDS = {"12345", "98765", "55321", "77001"}
    VALID_DOBS = {"june 10 1985", "april 2 1990", "march 15 1978", "january 5 2000"}

    def call(self, inputs: dict[str, Any], behavior: str = "normal") -> dict[str, Any]:
        if behavior == "timeout":
            time.sleep(0.1)
            return {"success": False, "error": "timeout", "verified": False}
        if behavior == "malformed_response":
            return {"verified": None, "status": object()}  # unparseable
        if behavior == "server_error":
            return {"success": False, "error": "500 Internal Server Error", "verified": False}
        if behavior == "empty_result":
            return {"success": True, "verified": False, "result": None}

        text = inputs.get("input", "").lower()
        has_valid_id = any(mid in text for mid in self.VALID_MEMBER_IDS)
        has_valid_dob = any(dob in text for dob in self.VALID_DOBS)
        # Also accept numeric patterns as "plausible" verification
        has_numbers = sum(1 for c in text if c.isdigit()) >= 4

        verified = (has_valid_id or has_numbers) and (has_valid_dob or has_numbers)
        return {
            "success": True,
            "verified": verified,
            "member_id": "M-12345" if has_valid_id else None,
            "message": "Identity verified successfully." if verified else "Verification failed.",
        }
