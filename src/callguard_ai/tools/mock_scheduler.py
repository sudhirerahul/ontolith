"""Mock appointment scheduler tool."""
from __future__ import annotations
import time
import random
from typing import Any


class MockSchedulerTool:
    CONFIRMATION_PREFIX = "CGQ"
    _counter = 1000

    def call(self, inputs: dict[str, Any], behavior: str = "normal") -> dict[str, Any]:
        if behavior == "timeout":
            time.sleep(0.12)
            return {"success": False, "error": "timeout", "booked": False}
        if behavior == "server_error":
            return {"success": False, "error": "500 Internal Server Error", "booked": False}
        if behavior == "empty_result":
            return {"success": True, "booked": False, "slots_available": []}
        if behavior == "malformed_response":
            return {"success": True, "booked": None, "confirmation_number": []}

        MockSchedulerTool._counter += 1
        conf_num = f"{self.CONFIRMATION_PREFIX}-{MockSchedulerTool._counter}"
        slots = inputs.get("slots", {})
        return {
            "success": True,
            "booked": True,
            "confirmation_number": conf_num,
            "scheduled_for": slots.get("appointment_date", slots.get("preferred_day", "the requested time")),
            "reminder_sent": True,
        }
