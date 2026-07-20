"""
Data models for test scenarios loaded from YAML.
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class ConversationStep(BaseModel):
    turn: int
    user: str
    perturbations: list[str] = Field(default_factory=list)
    tool_simulation: dict[str, Any] | None = None
    expected_agent_behavior: dict[str, Any] = Field(default_factory=dict)


class Expected(BaseModel):
    tool_calls: list[str] = Field(default_factory=list)
    tool_call_order: list[str] | None = None
    final_outcome: str = ""
    must_say_any: list[str] = Field(default_factory=list)
    must_not_say_any: list[str] = Field(default_factory=list)
    taxonomy_if_failed: list[str] = Field(default_factory=list)
    assembled_slot: dict[str, Any] | None = None


class Thresholds(BaseModel):
    max_latency_ms: int = 5000
    max_turns_to_completion: int = 10
    max_identical_responses: int = 2
    max_silence_prompts: int = 3


class PassCriteria(BaseModel):
    task_completed: bool = False
    tool_called_correctly: bool = False
    no_security_violations: bool = True
    no_compliance_violations: bool = True
    no_hallucination: bool = False
    context_retention: bool = False
    interruption_recovery: bool = False
    disclaimer_delivered_before_advice: bool = False
    emergency_escalated: bool = False
    graceful_fallback: bool = False
    required_behavior_match: float = 0.0


class Scenario(BaseModel):
    scenario_id: str
    name: str
    category: str
    tags: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    persona: str = "standard_caller"
    description: str = ""
    starting_context: dict[str, Any] = Field(default_factory=dict)
    conversation_steps: list[ConversationStep] = Field(default_factory=list)
    expected: Expected = Field(default_factory=Expected)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    pass_criteria: PassCriteria = Field(default_factory=PassCriteria)

    # --- Retail extensions (additive, backward compatible) ---
    difficulty: str = "medium"                                   # low | medium | high | expert
    persona_profile: dict[str, Any] = Field(default_factory=dict)  # structured persona metadata
    objection_chain: list[str] = Field(default_factory=list)       # ordered objection tags
    source: str = "static"                                        # static | dynamic | playbook | golden
