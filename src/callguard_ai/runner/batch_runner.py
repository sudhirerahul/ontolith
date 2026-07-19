"""
Batch Runner — orchestrates scenario execution, evaluation, and verdict.

Now supports three modes:
  1. Static   — runs fixed YAML scenarios against mock agents (original)
  2. LLM      -- runs fixed YAML scenarios against OpenRouter LLM agents
  3. Foundry  -- runs against Azure AI Foundry agent; scenarios can be
                 static YAML, dynamically LLM-generated, or both combined.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult
from ..models.evaluation import EvaluationResult, ComparisonResult
from ..models.verdict import ReleaseVerdict
from ..agents.adapters import BaselineAgentAdapter, CandidateAgentAdapter
from ..evaluators.engine import evaluate
from ..gate.release_gate import ReleaseGate
from ..utils.io import load_all_scenarios_raw, save_json, ensure_dir
from ..utils.diffing import diff_transcripts, find_tool_call_differences
from .scenario_runner import ScenarioRunner

console = Console()


def _parse_scenario(raw: dict) -> Scenario | None:
    try:
        return Scenario.model_validate(raw)
    except Exception as e:
        console.print(f"[yellow]⚠ Skipping malformed scenario: {e}[/yellow]")
        return None


class BatchRunner:
    def __init__(
        self,
        project_root: Path,
        enable_perturbations: bool = False,
        inject_mock_latency: bool = True,
        use_foundry: bool = False,
        dynamic_scenarios: bool = False,
        dynamic_only: bool = False,
        dynamic_count_per_category: int = 2,
        dynamic_categories: list[str] | None = None,
    ) -> None:
        self.project_root = project_root
        self.scenarios_dir = project_root / "scenarios"
        self.runs_dir = project_root / "runs"
        self.reports_dir = project_root / "reports"
        self.config_dir = project_root / "config"
        self.use_foundry = use_foundry
        self.dynamic_scenarios = dynamic_scenarios
        self.dynamic_only = dynamic_only
        self.dynamic_count_per_category = dynamic_count_per_category
        self.dynamic_categories = dynamic_categories or [
            "security", "compliance", "regression", "voice_robustness", "reliability"
        ]

        self.runner = ScenarioRunner(
            runs_dir=self.runs_dir,
            enable_perturbations=enable_perturbations,
            inject_mock_latency=inject_mock_latency,
        )
        self.gate = ReleaseGate(config_dir=self.config_dir)

    def _load_scenarios(
        self,
        category: str | None = None,
        scenario_id: str | None = None,
    ) -> list[Scenario]:
        """Load static YAML scenarios, dynamic LLM-generated ones, or both."""
        scenarios: list[Scenario] = []

        # Static YAML scenarios
        all_raw = load_all_scenarios_raw(self.scenarios_dir)
        for raw in all_raw:
            s = _parse_scenario(raw)
            if s:
                if category and s.category != category:
                    continue
                if scenario_id and s.scenario_id != scenario_id:
                    continue
                scenarios.append(s)

        # Dynamic LLM-generated scenarios

        if self.dynamic_scenarios and not scenario_id:
            console.print("\n[bold cyan]🧠 Generating dynamic LLM test scenarios...[/bold cyan]")
            try:
                from ..scenarios.dynamic_generator import DynamicScenarioGenerator
                agent_prompt = self._get_candidate_system_prompt()
                if agent_prompt:
                    console.print("  [green]Agent-aware mode:[/green] targeting your Foundry agent's rules")
                else:
                    console.print("  [yellow]Domain-aware mode[/yellow]")

                gen = DynamicScenarioGenerator(agent_system_prompt=agent_prompt)
                dynamic_only = getattr(self, 'dynamic_only', False)
                if dynamic_only:
                    dynamic = gen.generate_variety()
                    scenarios = []
                else:
                    cats = [category] if category else self.dynamic_categories
                    dynamic = gen.generate(
                        categories=cats,
                        count_per_category=self.dynamic_count_per_category,
                    )

                console.print(f"[green]✓ Generated {len(dynamic)} dynamic scenario(s)[/green]")
                scenarios.extend(dynamic)
            except Exception as e:
                console.print(f"[yellow]⚠ Dynamic generation failed: {e}[/yellow]")

        return scenarios

    def _get_candidate_system_prompt(self) -> str | None:
        # Explicit override wins
        explicit = os.environ.get("AZURE_FOUNDRY_SYSTEM_PROMPT", "")
        if explicit:
            return explicit

        if self.use_foundry:
            # Try to fetch live prompt from Foundry API first
            try:
                from ..agents.foundry_agent import fetch_live_agent_prompt
                live = fetch_live_agent_prompt()
                if live:
                    return live
            except Exception:
                pass
            # Fall back to hardcoded copy in Python file
            try:
                from ..agents.foundry_agent import HEALTHCARE_SYSTEM_PROMPT
                return HEALTHCARE_SYSTEM_PROMPT
            except ImportError:
                pass

        return None

    def _build_agents(self):
        """Return (baseline_agent, candidate_agent) based on mode."""
        if self.use_foundry:
            from ..agents.foundry_agent import FoundryAgentAdapter
            # Baseline: strong-prompt OpenRouter LLM (or mock if no key)
            baseline = BaselineAgentAdapter()
            # Candidate: your actual Azure Foundry deployment
            candidate = FoundryAgentAdapter()
            return baseline, candidate
        else:
            return BaselineAgentAdapter(), CandidateAgentAdapter()

    def run_all(
        self,
        category: str | None = None,
        scenario_id: str | None = None,
    ) -> ReleaseVerdict:
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        console.rule(f"[bold cyan]CallGuard AI — Run {run_id}[/bold cyan]")

        scenarios = self._load_scenarios(category, scenario_id)

        if not scenarios:
            console.print("[red]No matching scenarios found.[/red]")
            return ReleaseVerdict(verdict="PASS", run_id=run_id)

        static_count = sum(1 for s in scenarios if "dynamic" not in s.tags)
        dynamic_count = sum(1 for s in scenarios if "dynamic" in s.tags)
        console.print(f"[green]Loaded {len(scenarios)} scenario(s)[/green] "
                      f"([white]{static_count} static[/white] + "
                      f"[cyan]{dynamic_count} dynamic[/cyan])")

        baseline, candidate = self._build_agents()

        evaluations_baseline: list[EvaluationResult] = []
        evaluations_candidate: list[EvaluationResult] = []
        comparisons: list[ComparisonResult] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("Running scenarios...", total=len(scenarios) * 2)

            for scenario in scenarios:
                tag = "[cyan](dynamic)[/cyan]" if "dynamic" in scenario.tags else ""

                # Run baseline
                progress.update(task, description=f"[cyan]BASELINE[/cyan] {scenario.scenario_id} {tag}")
                b_result = self.runner.run(scenario, baseline, run_id)
                b_eval = evaluate(scenario, b_result)
                evaluations_baseline.append(b_eval)
                save_json(b_eval.model_dump(), self.runs_dir / run_id / scenario.scenario_id / "baseline_eval.json")
                progress.advance(task)

                # Run candidate
                progress.update(task, description=f"[yellow]CANDIDATE[/yellow] {scenario.scenario_id} {tag}")
                c_result = self.runner.run(scenario, candidate, run_id)
                c_eval = evaluate(scenario, c_result)
                evaluations_candidate.append(c_eval)
                save_json(c_eval.model_dump(), self.runs_dir / run_id / scenario.scenario_id / "candidate_eval.json")
                progress.advance(task)

                # Comparison
                comp = self._compare(scenario, b_result, c_result, b_eval, c_eval)
                comparisons.append(comp)
                save_json(comp.model_dump(), self.runs_dir / run_id / scenario.scenario_id / "comparison.json")

        verdict = self.gate.compute_verdict(
            run_id=run_id,
            evaluations=evaluations_candidate,
            comparisons=comparisons,
            baseline_evaluations=evaluations_baseline,
        )
        save_json(verdict.model_dump(), self.runs_dir / run_id / "verdict.json")
        self._print_summary(verdict, evaluations_candidate, comparisons)
        return verdict

    def _compare(self, scenario, b_result, c_result, b_eval, c_eval) -> ComparisonResult:
        score_delta = c_eval.overall_score - b_eval.overall_score
        regressions, improvements, new_failures = [], [], []

        for b_dim in b_eval.dimensions:
            c_dim = next((d for d in c_eval.dimensions if d.name == b_dim.name), None)
            if c_dim:
                delta = c_dim.score - b_dim.score
                if delta < -0.1:
                    regressions.append(f"{b_dim.name}: {b_dim.score:.2f} → {c_dim.score:.2f}")
                elif delta > 0.1:
                    improvements.append(f"{b_dim.name}: {b_dim.score:.2f} → {c_dim.score:.2f}")

        b_codes = {e.code for e in b_eval.failure_taxonomy}
        c_codes = {e.code for e in c_eval.failure_taxonomy}
        new_failures = sorted(c_codes - b_codes)

        b_latency = sum(t.latency_ms for t in b_result.transcript)
        c_latency = sum(t.latency_ms for t in c_result.transcript)

        if c_eval.pii_leakage_detected or c_eval.verification_bypass_detected:
            verdict_contribution = "block"
        elif regressions or new_failures:
            verdict_contribution = "warn"
        else:
            verdict_contribution = "neutral"

        return ComparisonResult(
            scenario_id=scenario.scenario_id,
            baseline_score=b_eval.overall_score,
            candidate_score=c_eval.overall_score,
            score_delta=round(score_delta, 1),
            baseline_passed=b_eval.passed,
            candidate_passed=c_eval.passed,
            regressions=regressions,
            improvements=improvements,
            new_failures=new_failures,
            latency_delta_ms=c_latency - b_latency,
            verdict_contribution=verdict_contribution,
        )

    def _print_summary(self, verdict, evaluations, comparisons) -> None:
        console.print()
        color = {"PASS": "green", "WARN": "yellow", "BLOCK": "red"}.get(verdict.verdict, "white")
        console.rule(f"[bold {color}]VERDICT: {verdict.verdict}[/bold {color}]")
        console.print(f"  Overall Score: [bold]{verdict.overall_score:.1f}/100[/bold]")
        console.print(f"  Security Score: {verdict.security_score:.1f}/100")
        console.print(f"  Compliance Score: {verdict.compliance_score:.1f}/100")
        console.print(f"  Stability Score: {verdict.stability_score:.1f}/100")
        console.print()

        table = Table(title="Scenario Results", show_lines=True)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Type")
        table.add_column("Baseline")
        table.add_column("Candidate")
        table.add_column("Delta")
        table.add_column("Status")

        for comp in comparisons:
            delta_color = "green" if comp.score_delta >= 0 else "red"
            status = "✅ PASS" if comp.candidate_passed else "❌ FAIL"
            status_color = "green" if comp.candidate_passed else "red"
            # Find if dynamic
            eval_match = next((e for e in evaluations if e.scenario_id == comp.scenario_id), None)
            type_label = "[cyan]dynamic[/cyan]" if eval_match and "llm-generated" in getattr(eval_match, 'notes', []) else "static"

            table.add_row(
                comp.scenario_id,
                type_label,
                f"{comp.baseline_score:.1f}",
                f"{comp.candidate_score:.1f}",
                f"[{delta_color}]{comp.score_delta:+.1f}[/{delta_color}]",
                f"[{status_color}]{status}[/{status_color}]",
            )

        console.print(table)

        if verdict.block_reasons:
            console.print("\n[bold red]🚫 BLOCK Reasons:[/bold red]")
            for r in verdict.block_reasons:
                console.print(f"  • {r.description}")

        if verdict.warn_reasons:
            console.print("\n[bold yellow]⚠ WARN Reasons:[/bold yellow]")
            for r in verdict.warn_reasons:
                console.print(f"  • {r.description}")

        if verdict.failure_taxonomy_counts:
            console.print("\n[bold]Failure Taxonomy:[/bold]")
            for code, count in sorted(verdict.failure_taxonomy_counts.items(), key=lambda x: -x[1]):
                console.print(f"  {code}: {count}")
        console.print()
