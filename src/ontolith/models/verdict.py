"""
Data models for the final release gate verdict.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class VerdictReason(BaseModel):
    rule_id: str
    description: str
    scenario_ids: list[str] = Field(default_factory=list)
    severity: str = "info"


class ReleaseVerdict(BaseModel):
    verdict: str                    # PASS | WARN | BLOCK
    run_id: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # Aggregate scores
    overall_score: float = 0.0
    security_score: float = 0.0
    compliance_score: float = 0.0
    stability_score: float = 0.0
    risk_score: float = 0.0

    # Counts
    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    blocked_scenarios: int = 0
    warned_scenarios: int = 0

    # Key findings
    block_reasons: list[VerdictReason] = Field(default_factory=list)
    warn_reasons: list[VerdictReason] = Field(default_factory=list)
    top_regressions: list[str] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    compliance_findings: list[str] = Field(default_factory=list)
    reliability_findings: list[str] = Field(default_factory=list)

    # Taxonomy summary
    failure_taxonomy_counts: dict[str, int] = Field(default_factory=dict)

    # Category breakdown
    category_scores: dict[str, float] = Field(default_factory=dict)
