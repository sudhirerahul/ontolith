"""
Data model for structured root-cause analysis (Transcript Intelligence / Prompt Debugger).
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class RootCauseAnalysis(BaseModel):
    scenario_id: str
    run_id: str = ""
    conversation_summary: str = ""
    customer_concern: str = ""
    associate_response: str = ""
    missed_opportunity: str = ""
    expected_behavior: list[str] = Field(default_factory=list)
    likely_prompt_issue: str = ""
    suggested_prompt_change: str = ""
    regression_tests_affected: list[str] = Field(default_factory=list)
    llm_powered: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)
