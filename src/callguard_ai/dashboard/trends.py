"""
Quality trend aggregation for the Retail Quality Dashboard — scans historical `runs/`
artifacts (no database, same flat-file convention as the rest of this project) and buckets
retail_sales scenario results by "sales dimension" (discovery/financing/delivery/etc.)
across runs, ordered by time (run_id is a UTC timestamp prefix, so lexical sort == time sort).
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..utils.io import load_all_scenarios_raw, load_json
from ..utils.slug import slugify

KNOWN_DIMENSIONS = [
    "discovery", "financing", "competitor_pricing", "delivery",
    "warranty", "protection_plan", "rapport", "closing",
]


def _sales_dimension(raw_scenario: dict[str, Any]) -> str:
    chain = raw_scenario.get("objection_chain") or []
    if chain:
        return chain[-1]
    for tag in raw_scenario.get("tags", []):
        if tag in KNOWN_DIMENSIONS:
            return tag
    return "discovery"


def compute_quality_trends(project_root: Path, retailer: str | None = None) -> dict[str, Any]:
    scenarios_dir = project_root / "scenarios"
    runs_dir = project_root / "runs"
    if not runs_dir.exists():
        return {"dimension_series": {}, "trend_deltas": {}, "top_failures": []}

    scenario_lookup = {s["scenario_id"]: s for s in load_all_scenarios_raw(scenarios_dir)}
    retailer_slug = slugify(retailer) if retailer else None

    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir() and (d / "verdict.json").exists())

    dimension_series: dict[str, list[tuple[str, float]]] = defaultdict(list)
    taxonomy_totals: Counter = Counter()

    for run_dir in run_dirs:
        run_id = run_dir.name
        per_dim_scores: dict[str, list[float]] = defaultdict(list)

        for scenario_dir in run_dir.iterdir():
            if not scenario_dir.is_dir():
                continue
            sid = scenario_dir.name
            raw_scenario = scenario_lookup.get(sid)
            if not raw_scenario or raw_scenario.get("category") != "retail_sales":
                continue
            if retailer_slug and retailer_slug not in raw_scenario.get("tags", []):
                continue

            eval_path = scenario_dir / "candidate_eval.json"
            if not eval_path.exists():
                continue
            ev = load_json(eval_path)
            checks = ev.get("raw_checks", {})
            if "discovery_score" not in checks:
                continue  # not a retail evaluation

            combined = (checks.get("discovery_score", 0.0) + checks.get("objection_resolution_score", 0.0)) / 2
            dim = _sales_dimension(raw_scenario)
            per_dim_scores[dim].append(combined)

            for entry in ev.get("failure_taxonomy", []):
                taxonomy_totals[entry["code"]] += 1

        for dim, scores in per_dim_scores.items():
            if scores:
                dimension_series[dim].append((run_id, round(sum(scores) / len(scores) * 100, 1)))

    trend_deltas: dict[str, float] = {}
    for dim, series in dimension_series.items():
        if len(series) >= 2:
            trend_deltas[dim] = round(series[-1][1] - series[0][1], 1)
        else:
            trend_deltas[dim] = 0.0

    return {
        "dimension_series": dict(dimension_series),
        "trend_deltas": trend_deltas,
        "top_failures": taxonomy_totals.most_common(10),
    }
