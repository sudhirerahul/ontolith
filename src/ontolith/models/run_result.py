"""
Data models for run artifacts — transcripts, tool events, metadata.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class TurnRecord(BaseModel):
    turn: int
    user_input: str
    agent_response: str
    tool_calls_made: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: int = 0
    perturbations_applied: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ToolEvent(BaseModel):
    turn: int
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    latency_ms: int = 0
    error: str | None = None
    behavior_simulated: str = "normal"


class RunMetadata(BaseModel):
    run_id: str
    scenario_id: str
    scenario_name: str
    category: str
    risk_level: str
    agent_version: str
    started_at: str
    completed_at: str | None = None
    total_turns: int = 0
    total_latency_ms: int = 0
    perturbations_enabled: bool = False
    status: str = "running"  # running | completed | error


class AgentRunResult(BaseModel):
    """Result for one agent (baseline or candidate) against one scenario."""
    agent_version: str
    scenario_id: str
    metadata: RunMetadata
    transcript: list[TurnRecord] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    session_state: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
