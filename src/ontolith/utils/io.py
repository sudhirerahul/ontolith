"""
File I/O utilities — all storage is flat-file JSON/YAML, no database.
"""
from __future__ import annotations
import json
import yaml
from pathlib import Path
from typing import Any


def load_yaml(path: Path | str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_yaml_multi(path: Path | str) -> list[dict[str, Any]]:
    """Load a YAML file that may contain multiple documents (--- separated)."""
    with open(path, "r", encoding="utf-8") as f:
        return list(yaml.safe_load_all(f))


def save_json(data: Any, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(path: Path | str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_scenario_files(scenarios_dir: Path) -> list[Path]:
    """Recursively find all .yaml scenario files."""
    return sorted(scenarios_dir.rglob("*.yaml"))


def load_all_scenarios_raw(scenarios_dir: Path) -> list[dict[str, Any]]:
    """Load every YAML scenario file (including multi-doc files)."""
    all_scenarios: list[dict[str, Any]] = []
    for yaml_file in list_scenario_files(scenarios_dir):
        docs = load_yaml_multi(yaml_file)
        for doc in docs:
            if doc and isinstance(doc, dict) and "scenario_id" in doc:
                all_scenarios.append(doc)
    return all_scenarios
