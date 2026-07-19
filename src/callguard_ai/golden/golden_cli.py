"""CLI handlers for `callguard golden import/list/approve/reject`."""
from __future__ import annotations
import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .registry import GoldenRegistry
from .transcript_intake import import_customer_transcript


def cmd_golden_import(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    registry = GoldenRegistry(project_root)
    scenario, root_cause, issue_id = import_customer_transcript(
        args.transcript, args.retailer, scenarios_dir=project_root / "scenarios",
    )
    registry.add_pending(scenario, args.retailer, issue_id, root_cause)

    console.print(f"[green]✓ Imported customer issue {issue_id}[/green] as pending scenario "
                  f"[cyan]{scenario.scenario_id}[/cyan]")
    console.print(f"  Detected failure(s): {', '.join(scenario.expected.taxonomy_if_failed) or 'none'}")
    console.print(f"  Missed opportunity: {root_cause.missed_opportunity}")
    console.print(f"\n[dim]Review with: python -m callguard_ai golden list --status pending[/dim]")
    console.print(f"[dim]Approve with: python -m callguard_ai golden approve {scenario.scenario_id}[/dim]")


def cmd_golden_list(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    registry = GoldenRegistry(project_root)
    entries = registry.list(status=args.status)

    table = Table(title=f"Golden Dataset{f' — {args.status}' if args.status else ''}")
    table.add_column("Scenario ID", style="cyan")
    table.add_column("Retailer")
    table.add_column("Issue ID")
    table.add_column("Status")
    table.add_column("Created")
    status_colors = {"pending": "yellow", "approved": "green", "verified": "bold green", "rejected": "red"}
    for e in entries:
        status = e["status"]
        table.add_row(
            e["scenario_id"], e["retailer"], e["customer_issue_id"],
            f"[{status_colors.get(status, 'white')}]{status}[/{status_colors.get(status, 'white')}]",
            e.get("created_at", "")[:19],
        )
    console.print(table)
    if not entries:
        console.print("[dim]No entries. Import a transcript with `golden import`.[/dim]")


def cmd_golden_approve(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    registry = GoldenRegistry(project_root)
    try:
        entry = registry.approve(args.scenario_id)
    except (KeyError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return
    console.print(f"[green]✓ Approved {args.scenario_id}[/green] — now part of the permanent "
                  f"regression suite at [cyan]{entry['scenario_path']}[/cyan]")
    console.print("[dim]It will run automatically on every future `run --category retail_sales --retail`.[/dim]")


def cmd_golden_reject(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    registry = GoldenRegistry(project_root)
    try:
        registry.reject(args.scenario_id, args.reason)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        return
    console.print(f"[yellow]Rejected {args.scenario_id}[/yellow]" + (f" — {args.reason}" if args.reason else ""))
