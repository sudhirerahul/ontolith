"""
Abstract base class for all agent adapters.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseAgentAdapter(ABC):
    """
    Protocol that every agent adapter must implement.
    Allows the runner to test any agent implementation without code changes.
    """

    @abstractmethod
    def initialize_session(self, context: dict[str, Any]) -> dict[str, Any]:
        """Start a new conversation session. Returns session state."""
        ...

    @abstractmethod
    def send_user_turn(self, user_input: str, session_state: dict[str, Any]) -> str:
        """Send a user utterance. Returns the agent's text response."""
        ...

    @abstractmethod
    def get_tool_calls(self) -> list[str]:
        """Return list of tool names called during the last turn."""
        ...

    @abstractmethod
    def get_tool_events(self) -> list[dict[str, Any]]:
        """Return full tool event records from the last turn."""
        ...

    @abstractmethod
    def get_session_state(self) -> dict[str, Any]:
        """Return current session state (slots, flags, etc.)."""
        ...

    @abstractmethod
    def get_version(self) -> str:
        """Return the agent version string."""
        ...
