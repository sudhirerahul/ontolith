"""
Data models for Retail Roleplay Studio — customer personas and objection/product trees.
These are descriptive/browsable artifacts; the executable unit of work is still the
Scenario (models/scenario.py). Personas/trees are saved as JSON alongside generated
scenario YAMLs so the dashboard can render the hierarchy without re-parsing scenarios.
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class CustomerPersona(BaseModel):
    persona_id: str
    name: str
    motivation: str = ""
    budget_sensitivity: str = "medium"   # low | medium | high
    tone: str = "neutral"
    objections: list[str] = Field(default_factory=list)
    difficulty: str = "medium"


class ObjectionNode(BaseModel):
    node_id: str
    label: str
    children: list["ObjectionNode"] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)


class ProductHierarchy(BaseModel):
    retailer: str
    nodes: list[ObjectionNode] = Field(default_factory=list)


class RoleplaySet(BaseModel):
    """Top-level artifact written per retailer: personas.json / objection_tree.json source."""
    retailer: str
    generated_at: str = ""
    llm_powered: bool = False
    personas: list[CustomerPersona] = Field(default_factory=list)
    hierarchy: ProductHierarchy
    scenario_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
