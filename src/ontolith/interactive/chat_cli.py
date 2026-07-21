"""
Interactive live roleplay — chat turn-by-turn against a candidate agent instead of
running a pre-scripted YAML scenario. Reuses the same BaseAgentAdapter protocol and
turn-threading pattern as runner/scenario_runner.py (initialize_session ->
send_user_turn -> get_session_state each turn), so any adapter — mock, LLM, or a
real Foundry deployment — works here unchanged.

For retail sessions, the finished transcript can be handed straight to the golden
dataset pipeline (golden/transcript_intake.py) so a real live roleplay becomes a
permanent regression scenario the same way an imported customer transcript would.
"""
from __future__ import annotations
import argparse
import json
import os
import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt


def _build_agent(args: argparse.Namespace):
    if args.foundry:
        from ..agents.foundry_agent import FoundryAgentAdapter
        return FoundryAgentAdapter(), "your Azure AI Foundry deployment"

    if args.retail:
        from ..agents.retail_adapters import RetailBaselineAdapter, RetailCandidateAdapter
        if args.baseline:
            return RetailBaselineAdapter(), "retail baseline (discovers before resolving)"
        return RetailCandidateAdapter(), "retail candidate (skips discovery — the regression under test)"

    if args.llm:
        os.environ["USE_LLM_AGENT"] = "true"
    from ..agents.adapters import BaselineAgentAdapter, CandidateAgentAdapter
    if args.baseline:
        return BaselineAgentAdapter(), "healthcare baseline agent"
    return CandidateAgentAdapter(), "healthcare candidate agent"


def cmd_chat(args: argparse.Namespace, project_root: Path, console: Console) -> None:
    agent, label = _build_agent(args)

    console.print(Panel(
        f"Chatting with: [cyan]{label}[/cyan]  (version [dim]{agent.get_version()}[/dim])\n"
        f"You are playing the customer/caller. Type your message and press Enter.\n"
        f"Type [bold]exit[/bold] or [bold]quit[/bold] to end the session.",
        title="[bold]Interactive Roleplay[/bold]",
        border_style="cyan",
    ))

    session_state = agent.initialize_session({})
    turns: list[dict[str, str]] = []

    while True:
        try:
            user_input = Prompt.ask("\n[bold]You[/bold]")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user_input.strip() or user_input.strip().lower() in ("exit", "quit", "q"):
            break

        response = agent.send_user_turn(user_input, session_state=session_state)
        session_state = agent.get_session_state()

        turns.append({"role": "customer", "text": user_input})
        turns.append({"role": "associate", "text": response})

        console.print(f"[cyan]Agent[/cyan]: {response}")

    if not turns:
        console.print("[dim]No turns recorded — nothing to save.[/dim]")
        return

    console.print(f"\n[dim]Session ended — {len(turns) // 2} turn(s) recorded.[/dim]")

    if not args.retail:
        return  # golden dataset only supports the retail_sales category today

    try:
        if not Confirm.ask("Save this session as a golden dataset candidate?", default=False):
            return
        retailer = Prompt.ask("Retailer", default=args.retailer)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Skipped.[/dim]")
        return
    issue_id = f"CS-{uuid.uuid4().hex[:6]}"
    transcript = {
        "customer_issue_id": issue_id,
        "retailer": retailer,
        "channel": "interactive_chat",
        "turns": turns,
    }

    scratch_dir = project_root / "golden_dataset" / "interactive_transcripts"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = scratch_dir / f"{issue_id}.json"
    transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    from ..golden.registry import GoldenRegistry
    from ..golden.transcript_intake import import_customer_transcript

    scenario, root_cause, resolved_issue_id, resolved_retailer = import_customer_transcript(
        transcript_path, retailer, scenarios_dir=project_root / "scenarios",
    )
    registry = GoldenRegistry(project_root)
    try:
        registry.add_pending(scenario, resolved_retailer, resolved_issue_id, root_cause)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(f"[green]Saved as pending golden scenario[/green] [cyan]{scenario.scenario_id}[/cyan]")
    console.print(f"  Missed opportunity: {root_cause.missed_opportunity}")
    console.print("[dim]Review with: python -m ontolith golden list --status pending[/dim]")
    console.print(f"[dim]Approve with: python -m ontolith golden approve {scenario.scenario_id}[/dim]")
