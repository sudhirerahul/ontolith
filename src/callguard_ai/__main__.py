"""
CallGuard AI — CLI entrypoint.

MODES:
  Deterministic (no keys needed):
    python -m callguard_ai run --all

  LLM mode (OpenRouter key):
    python -m callguard_ai run --all --llm

  Foundry mode (Azure key + OpenRouter key for judge):
    python -m callguard_ai run --all --foundry

  Dynamic scenarios (LLM generates fresh test cases):
    python -m callguard_ai run --all --dynamic
    python -m callguard_ai run --all --foundry --dynamic

  Control dynamic generation:
    python -m callguard_ai run --all --dynamic --dynamic-count 3
    python -m callguard_ai run --all --dynamic --dynamic-categories security compliance

OTHER COMMANDS:
  python -m callguard_ai list
  python -m callguard_ai report --latest
  python -m callguard_ai dashboard
  python -m callguard_ai setup         ← prints setup instructions
"""
from __future__ import annotations
import sys
import os
import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _find_project_root() -> Path:
    # Always resolve relative to this file's location, not cwd
    # This file is at: src/callguard_ai/__main__.py
    # Project root is:  ../../  (two levels up)
    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent  # up from __main__.py → callguard_ai → src → root
    if (project_root / "config").exists() and (project_root / "scenarios").exists():
        return project_root
    # Fallback: search upward
    candidate = this_file
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "config").exists() and (candidate / "scenarios").exists():
            return candidate
    return Path.cwd()

PROJECT_ROOT = _find_project_root()


def _print_mode_banner(args: argparse.Namespace) -> None:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    foundry_endpoint = os.environ.get("AZURE_FOUNDRY_PROJECT_ENDPOINT", "") or os.environ.get("AZURE_OPENAI_ENDPOINT", "") or os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
    foundry_key = os.environ.get("AZURE_FOUNDRY_KEY", "")

    if args.foundry:
        if foundry_endpoint and foundry_key:
            model = os.environ.get("AZURE_FOUNDRY_MODEL", "phi-4-mini")
            judge = "LLM judge (OpenRouter)" if openrouter_key else "Deterministic fallback"
            dynamic_note = f"\nDynamic scenarios: [cyan]ON ({args.dynamic_count}/category × {len(args.dynamic_categories or ['all'])} categories)[/cyan]" if args.dynamic else "\nDynamic scenarios: OFF (static YAML only)"
            console.print(Panel(
                f"[bold green]☁ AZURE FOUNDRY MODE[/bold green]\n"
                f"Agent under test: [cyan]{model}[/cyan] (your Foundry deployment)\n"
                f"Baseline agent: OpenRouter Llama 3.1 (strong system prompt)\n"
                f"Evaluator: {judge}"
                f"{dynamic_note}",
                title="[bold]Evaluation Mode[/bold]",
                border_style="green",
            ))
        else:
            missing = []
            if not foundry_endpoint:
                missing.append("AZURE_FOUNDRY_ENDPOINT")
            if not foundry_key:
                missing.append("AZURE_FOUNDRY_KEY")
            console.print(Panel(
                f"[bold red]⚠ --foundry flag set but credentials missing[/bold red]\n"
                f"Missing: [red]{', '.join(missing)}[/red]\n\n"
                f"Run: [cyan]python -m callguard_ai setup[/cyan] for instructions.",
                title="[bold]Setup Required[/bold]",
                border_style="red",
            ))
    elif args.llm:
        if openrouter_key:
            console.print(Panel(
                "[bold green]🤖 LLM MODE[/bold green]\n"
                "Agents: OpenRouter free LLM (Llama 3.1 8B)\n"
                "Candidate regression: weakened system prompt vs hardened baseline\n"
                "Evaluator: LLM judge reasoning",
                title="[bold]Evaluation Mode[/bold]",
                border_style="green",
            ))
        else:
            console.print(Panel(
                "[bold yellow]⚠ --llm flag set but OPENROUTER_API_KEY not found[/bold yellow]\n"
                "Falling back to deterministic mode.\n"
                "Get a free key at: [cyan]https://openrouter.ai[/cyan]",
                title="[bold]LLM Mode Unavailable[/bold]",
                border_style="yellow",
            ))
    else:
        dynamic_note = f"\nDynamic scenarios: [cyan]ON[/cyan]" if args.dynamic else ""
        console.print(Panel(
            "[bold blue]⚙ DETERMINISTIC MODE[/bold blue]\n"
            "Agents: Mock rule-based (no API keys needed)\n"
            "Evaluator: LLM judge with deterministic fallback"
            f"{dynamic_note}\n"
            "Tip: Add [cyan]--foundry[/cyan] to test your Azure AI Foundry agent",
            title="[bold]Evaluation Mode[/bold]",
            border_style="blue",
        ))


def cmd_run(args: argparse.Namespace) -> None:
    from .runner.batch_runner import BatchRunner
    from .reporting.html_report import generate_html_report

    if args.llm:
        os.environ["USE_LLM_AGENT"] = "true"

    _print_mode_banner(args)

    dynamic_categories = args.dynamic_categories if args.dynamic_categories else None

    dynamic_only = getattr(args, 'dynamic_only', False)

    runner = BatchRunner(
        project_root=PROJECT_ROOT,
        enable_perturbations=args.perturbations,
        inject_mock_latency=not args.no_latency,
        use_foundry=args.foundry,
        dynamic_scenarios=args.dynamic or dynamic_only,
        dynamic_only=dynamic_only,
        dynamic_count_per_category=args.dynamic_count,
        dynamic_categories=dynamic_categories,
    )

    verdict = runner.run_all(
        category=args.category,
        scenario_id=args.scenario,
    )

    runs_dir = PROJECT_ROOT / "runs" / verdict.run_id
    comparisons = []
    for scenario_dir in runs_dir.iterdir():
        if scenario_dir.is_dir():
            comp_file = scenario_dir / "comparison.json"
            if comp_file.exists():
                comparisons.append(json.loads(comp_file.read_text()))

    report_path = generate_html_report(
        verdict=verdict,
        comparisons=comparisons,
        reports_dir=PROJECT_ROOT / "reports",
    )

    console.print(f"\n[green]✓[/green] HTML report: [cyan]{report_path}[/cyan]")
    console.print(f"[green]✓[/green] Artifacts: [cyan]{runs_dir}[/cyan]\n")

    color = {"PASS": "green", "WARN": "yellow", "BLOCK": "red"}.get(verdict.verdict, "white")
    console.print(Panel(
        f"[bold {color}]{verdict.verdict}[/bold {color}]  |  "
        f"Score: [bold]{verdict.overall_score:.1f}[/bold]  |  "
        f"Security: {verdict.security_score:.1f}  |  "
        f"Compliance: {verdict.compliance_score:.1f}",
        title="[bold]Release Verdict[/bold]",
        border_style=color,
    ))


def cmd_report(args: argparse.Namespace) -> None:
    from .reporting.html_report import generate_html_report
    from .models.verdict import ReleaseVerdict

    runs_dir = PROJECT_ROOT / "runs"
    if args.latest:
        run_dirs = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir() and (d / "verdict.json").exists()],
            reverse=True,
        )
        if not run_dirs:
            console.print("[red]No completed runs found.[/red]")
            return
        run_id = run_dirs[0].name
    else:
        run_id = args.run

    verdict_file = runs_dir / run_id / "verdict.json"
    if not verdict_file.exists():
        console.print(f"[red]Verdict not found for run: {run_id}[/red]")
        return

    verdict = ReleaseVerdict.model_validate(json.loads(verdict_file.read_text()))
    comparisons = []
    for scenario_dir in (runs_dir / run_id).iterdir():
        if scenario_dir.is_dir():
            comp_file = scenario_dir / "comparison.json"
            if comp_file.exists():
                comparisons.append(json.loads(comp_file.read_text()))

    report_path = generate_html_report(
        verdict=verdict,
        comparisons=comparisons,
        reports_dir=PROJECT_ROOT / "reports",
    )
    console.print(f"[green]✓[/green] Report: [cyan]{report_path}[/cyan]")


def cmd_dashboard(_args: argparse.Namespace) -> None:
    import subprocess
    app_path = Path(__file__).parent / "reporting" / "streamlit_app.py"
    console.print("[cyan]Starting Streamlit dashboard...[/cyan]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=False)


def cmd_list(_args: argparse.Namespace) -> None:
    from .utils.io import load_all_scenarios_raw
    all_raw = load_all_scenarios_raw(PROJECT_ROOT / "scenarios")

    table = Table(title="Static Scenarios (YAML)", show_lines=False)
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Risk")
    for raw in all_raw:
        table.add_row(raw.get("scenario_id", ""), raw.get("name", ""),
                      raw.get("category", ""), raw.get("risk_level", ""))
    console.print(table)
    console.print("\n[dim]+ dynamic scenarios are generated fresh each run with [cyan]--dynamic[/cyan][/dim]")


def cmd_setup(_args: argparse.Namespace) -> None:
    console.print(Panel(
        "[bold cyan]CallGuard AI — Setup Guide[/bold cyan]\n\n"
        "[bold]1. OpenRouter (free LLM judge + LLM agents)[/bold]\n"
        "   → Go to [cyan]https://openrouter.ai[/cyan] and sign up (no card needed)\n"
        "   → Copy your API key\n"
        "   → Run: [cyan]set OPENROUTER_API_KEY=your_key_here[/cyan]\n\n"
        "[bold]2. Azure AI Foundry (the agent being tested)[/bold]\n"
        "   → Go to [cyan]https://ai.azure.com[/cyan]\n"
        "   → Create a project → Models + endpoints → Deploy model\n"
        "   → Choose [cyan]phi-4-mini[/cyan] (serverless, free tier)\n"
        "   → Copy the Endpoint URL and Key from the deployment page\n"
        "   → Run:\n"
        "       [cyan]set AZURE_FOUNDRY_ENDPOINT=https://your-endpoint.inference.ai.azure.com[/cyan]\n"
        "       [cyan]set AZURE_FOUNDRY_KEY=your_key_here[/cyan]\n"
        "       [cyan]set AZURE_FOUNDRY_MODEL=phi-4-mini[/cyan]\n\n"
        "[bold]3. Verify setup[/bold]\n"
        "   → [cyan]python -m callguard_ai run --scenario SEC_001 --foundry[/cyan]\n\n"
        "[bold]4. Full run with dynamic scenarios[/bold]\n"
        "   → [cyan]python -m callguard_ai run --all --foundry --dynamic[/cyan]",
        title="Setup Instructions",
        border_style="cyan",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="callguard_ai",
        description="🛡 CallGuard AI — Voice AI Release Validation Gate",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run test scenarios")
    scope = run_p.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", default=True)
    scope.add_argument("--category", type=str, help="Filter by category")
    scope.add_argument("--scenario", type=str, help="Single scenario ID")

    run_p.add_argument("--perturbations", action="store_true")
    run_p.add_argument("--no-latency", action="store_true")

    # Agent mode flags
    agent_mode = run_p.add_mutually_exclusive_group()
    agent_mode.add_argument("--llm", action="store_true",
                            help="Use OpenRouter LLM agents (needs OPENROUTER_API_KEY)")
    agent_mode.add_argument("--foundry", action="store_true",
                            help="Test your Azure AI Foundry agent (needs AZURE_FOUNDRY_* vars)")

    # Dynamic scenario flags
    run_p.add_argument("--dynamic", action="store_true",
                       help="Generate additional LLM-created test cases each run")
    run_p.add_argument("--dynamic-only", action="store_true", dest="dynamic_only",
                       help="Run ONLY 5 dynamic variety tests (1 per category) — fastest demo mode")
    run_p.add_argument("--dynamic-count", type=int, default=2, dest="dynamic_count",
                       help="Dynamic scenarios per category (default: 2)")
    run_p.add_argument("--dynamic-categories", nargs="+", dest="dynamic_categories",
                       choices=["security", "compliance", "regression", "voice_robustness", "reliability"],
                       help="Which categories to generate dynamic scenarios for")

    # ── report ───────────────────────────────────────────────────────────────
    rep_p = sub.add_parser("report", help="Generate HTML report")
    rep_g = rep_p.add_mutually_exclusive_group(required=True)
    rep_g.add_argument("--latest", action="store_true")
    rep_g.add_argument("--run", type=str)

    # ── other ────────────────────────────────────────────────────────────────
    sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    sub.add_parser("list", help="List static scenarios")
    sub.add_parser("setup", help="Print setup instructions for Azure Foundry + OpenRouter")

    args = parser.parse_args()
    # Set defaults for dynamic flags if not present
    if not hasattr(args, "dynamic"):
        args.dynamic = False
    if not hasattr(args, "dynamic_count"):
        args.dynamic_count = 2
    if not hasattr(args, "dynamic_categories"):
        args.dynamic_categories = None
    if not hasattr(args, "llm"):
        args.llm = False
    if not hasattr(args, "foundry"):
        args.foundry = False

    {
        "run": cmd_run,
        "report": cmd_report,
        "dashboard": cmd_dashboard,
        "list": cmd_list,
        "setup": cmd_setup,
    }[args.command](args)


if __name__ == "__main__":
    main()
