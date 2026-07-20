"""CLI handler for `ontolith debug show` — renders a root_cause.json as a Rich panel."""
from __future__ import annotations
import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..utils.io import load_json


def cmd_debug_show(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    path = project_root / "runs" / args.run_id / args.scenario_id / "root_cause.json"
    if not path.exists():
        console.print(
            f"[red]No root-cause analysis found for {args.scenario_id} in run {args.run_id}.[/red]\n"
            f"[dim]It's only generated for scenarios that failed or scored below 70.[/dim]"
        )
        return

    data = load_json(path)
    mode = "[green]LLM-powered[/green]" if data.get("llm_powered") else "[yellow]deterministic fallback[/yellow]"

    body = (
        f"[bold]Conversation Summary[/bold]\n{data.get('conversation_summary', '')}\n\n"
        f"[bold]Customer Concern[/bold]\n{data.get('customer_concern', '')}\n\n"
        f"[bold]Associate Response[/bold]\n{data.get('associate_response', '')}\n\n"
        f"[bold red]Missed Opportunity[/bold red]\n{data.get('missed_opportunity', '')}\n\n"
        f"[bold]Expected Behavior[/bold]\n" +
        "\n".join(f"  {i+1}. {step}" for i, step in enumerate(data.get("expected_behavior", []))) + "\n\n"
        f"[bold]Likely Prompt Issue[/bold]\n{data.get('likely_prompt_issue', '')}\n\n"
        f"[bold cyan]Suggested Prompt Change[/bold cyan]\n{data.get('suggested_prompt_change', '')}\n\n"
        f"[bold]Regression Tests Affected[/bold]\n" +
        ("\n".join(f"  • {sid}" for sid in data.get("regression_tests_affected", [])) or "  (none)")
    )

    console.print(Panel(
        body,
        title=f"[bold]Root Cause — {data.get('scenario_id', args.scenario_id)}[/bold]  ({mode})",
        border_style="cyan",
    ))
