"""
Baseline and Candidate adapters for retail_sales scenarios.
Same shape as agents/adapters.py, wrapping RetailMockAgentCore instead of MockAgentCore.
"""
from __future__ import annotations
from typing import Any
from .base import BaseAgentAdapter
from .retail_mock_agent import RetailMockAgentCore


class RetailBaselineAdapter(BaseAgentAdapter):
    """Baseline retail associate — always discovers before resolving."""

    def __init__(self) -> None:
        self._core = RetailMockAgentCore(version="retail-baseline-v1.0.0", introduce_flaws=False)

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._core.initialize_session(context)

    def send_user_turn(self, user_input: str, session_state: dict[str, Any],
                       tool_simulation: dict[str, Any] | None = None) -> str:
        return self._core.send_user_turn(user_input, session_state, tool_simulation)

    def get_tool_calls(self) -> list[str]:
        return self._core.get_tool_calls()

    def get_tool_events(self) -> list[dict[str, Any]]:
        return self._core.get_tool_events()

    def get_session_state(self) -> dict[str, Any]:
        return self._core.get_session_state()

    def get_version(self) -> str:
        return self._core.version


class RetailCandidateAdapter(BaseAgentAdapter):
    """Candidate retail associate under test — skips discovery, jumps to resolution."""

    def __init__(self) -> None:
        self._core = RetailMockAgentCore(version="retail-candidate-v1.0.0-rc1", introduce_flaws=True)

    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._core.initialize_session(context)

    def send_user_turn(self, user_input: str, session_state: dict[str, Any],
                       tool_simulation: dict[str, Any] | None = None) -> str:
        return self._core.send_user_turn(user_input, session_state, tool_simulation)

    def get_tool_calls(self) -> list[str]:
        return self._core.get_tool_calls()

    def get_tool_events(self) -> list[dict[str, Any]]:
        return self._core.get_tool_events()

    def get_session_state(self) -> dict[str, Any]:
        return self._core.get_session_state()

    def get_version(self) -> str:
        return self._core.version
