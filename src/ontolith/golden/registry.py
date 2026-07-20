"""
Golden dataset registry — flat-file JSON tracking of the customer-issue → permanent
regression-test workflow. Same persistence style as everywhere else in this project
(utils/io.py's save_json/load_json), no database.

Statuses: pending -> approved -> verified, or pending -> rejected.
Approving moves the scenario YAML from golden_dataset/pending/ into
scenarios/golden/<retailer_slug>/, which BatchRunner picks up automatically via the
existing recursive scenario loader — no runner changes needed.
"""
from __future__ import annotations
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.scenario import Scenario
from ..models.analysis import RootCauseAnalysis
from ..utils.io import ensure_dir, load_json, save_json
from ..utils.slug import slugify

import yaml


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoldenRegistry:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.golden_dir = project_root / "golden_dataset"
        self.pending_dir = self.golden_dir / "pending"
        self.registry_path = self.golden_dir / "registry.json"
        self.scenarios_golden_dir = project_root / "scenarios" / "golden"

    def _load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"entries": {}}
        return load_json(self.registry_path)

    def _save(self, data: dict[str, Any]) -> None:
        save_json(data, self.registry_path)

    def add_pending(
        self,
        scenario: Scenario,
        retailer: str,
        customer_issue_id: str,
        root_cause: RootCauseAnalysis,
    ) -> None:
        data = self._load()
        existing = data["entries"].get(scenario.scenario_id)
        if existing and existing["status"] in ("approved", "verified"):
            raise ValueError(
                f"'{scenario.scenario_id}' is already {existing['status']} in the golden "
                f"dataset — re-importing would silently reset it to pending while its "
                f"promoted copy at {existing.get('scenario_path')} keeps running. "
                f"Reject it first (golden reject) if you really want to replace it."
            )

        ensure_dir(self.pending_dir)
        pending_path = self.pending_dir / f"{scenario.scenario_id}.yaml"
        with open(pending_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(scenario.model_dump(), f, sort_keys=False, allow_unicode=True)

        data["entries"][scenario.scenario_id] = {
            "scenario_id": scenario.scenario_id,
            "retailer": retailer,
            "customer_issue_id": customer_issue_id,
            "status": "pending",
            "created_at": _now(),
            "root_cause_summary": root_cause.missed_opportunity,
            "pending_path": str(pending_path.relative_to(self.project_root)),
        }
        self._save(data)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        entries = list(self._load()["entries"].values())
        if status:
            entries = [e for e in entries if e["status"] == status]
        return sorted(entries, key=lambda e: e.get("created_at", ""), reverse=True)

    def get(self, scenario_id: str) -> dict[str, Any] | None:
        return self._load()["entries"].get(scenario_id)

    def approve(self, scenario_id: str) -> dict[str, Any]:
        data = self._load()
        entry = data["entries"].get(scenario_id)
        if not entry:
            raise KeyError(f"No golden dataset entry for '{scenario_id}'")
        if entry["status"] != "pending":
            raise ValueError(f"'{scenario_id}' is not pending (status={entry['status']})")

        pending_path = self.project_root / entry["pending_path"]
        retailer_slug = slugify(entry["retailer"])
        target_dir = ensure_dir(self.scenarios_golden_dir / retailer_slug)
        target_path = target_dir / f"{scenario_id}.yaml"
        shutil.move(str(pending_path), str(target_path))

        entry["status"] = "approved"
        entry["approved_at"] = _now()
        entry["scenario_path"] = str(target_path.relative_to(self.project_root))
        self._save(data)
        return entry

    def reject(self, scenario_id: str, reason: str = "") -> dict[str, Any]:
        data = self._load()
        entry = data["entries"].get(scenario_id)
        if not entry:
            raise KeyError(f"No golden dataset entry for '{scenario_id}'")
        entry["status"] = "rejected"
        entry["rejected_at"] = _now()
        entry["reject_reason"] = reason
        self._save(data)
        return entry

    def mark_verified(self, scenario_id: str, run_id: str, passed: bool) -> None:
        """Called by BatchRunner after any run that includes an approved golden scenario."""
        data = self._load()
        entry = data["entries"].get(scenario_id)
        if not entry or entry["status"] not in ("approved", "verified"):
            return
        entry["last_run_id"] = run_id
        entry["last_run_passed"] = passed
        entry["last_checked_at"] = _now()
        if passed:
            entry["status"] = "verified"
            entry.setdefault("verified_run_ids", []).append(run_id)
        else:
            # Regressed again — demote back to approved (still enforced, but flagged)
            entry["status"] = "approved"
            entry["regressed_at"] = _now()
        self._save(data)

    def approved_scenario_ids(self) -> set[str]:
        return {
            sid for sid, e in self._load()["entries"].items()
            if e["status"] in ("approved", "verified")
        }
