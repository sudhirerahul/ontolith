"""Shared slugify helper — used for retailer directory names across playbook/golden modules."""
from __future__ import annotations
import re


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
