"""
Data models for evaluation results and scoring.
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    name: str
    score: float          # 0.0 – 1.0
    weight: int
    weighted_score: float
    passed: bool
    notes: list[str] = Field(default_factory=list)


class FailureTaxonomyEntry(BaseModel):
    code: str
    description: str
    severity: str         # critical | high | medium | low
    turn: int | None = None


class EvaluationResult(BaseModel):
    scenario_id: str
    agent_version: str
    dimensions: list[DimensionScore] = Field(default_factory=list)
    overall_score: float = 0.0
    risk_score: float = 0.0       # higher = riskier
    stability_score: float = 0.0
    failure_taxonomy: list[FailureTaxonomyEntry] = Field(default_factory=list)
    security_violations: list[str] = Field(default_factory=list)
    compliance_violations: list[str] = Field(default_factory=list)
    pii_leakage_detected: bool = False
    verification_bypass_detected: bool = False
    emergency_escalation_missed: bool = False
    passed: bool = False
    notes: list[str] = Field(default_factory=list)
    raw_checks: dict[str, Any] = Field(default_factory=dict)


class ComparisonResult(BaseModel):
    scenario_id: str
    baseline_score: float
    candidate_score: float
    score_delta: float
    baseline_passed: bool
    candidate_passed: bool
    regressions: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    new_failures: list[str] = Field(default_factory=list)
    latency_delta_ms: int = 0
    verdict_contribution: str = "neutral"  # block | warn | neutral
