"""
Scenario Runner — executes a single scenario against one agent adapter,
captures all artifacts, and writes them to the file system.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.scenario import Scenario
from ..models.run_result import AgentRunResult, RunMetadata, TurnRecord, ToolEvent
from ..agents.base import BaseAgentAdapter
from ..perturbations.text_mutators import apply_perturbations
from ..utils.io import save_json
from ..utils.timing import measure_ms, mock_latency


class ScenarioRunner:
    """
    Executes one scenario against one agent.
    Writes artifacts to: runs/<run_id>/<scenario_id>/<agent_version>/
    """

    def __init__(
        self,
        runs_dir: Path,
        enable_perturbations: bool = False,
        inject_mock_latency: bool = True,
    ) -> None:
        self.runs_dir = runs_dir
        self.enable_perturbations = enable_perturbations
        self.inject_mock_latency = inject_mock_latency

    def run(
        self,
        scenario: Scenario,
        agent: BaseAgentAdapter,
        run_id: str,
    ) -> AgentRunResult:
        agent_version = agent.get_version()
        started_at = datetime.utcnow().isoformat()

        # Initialize session
        session_state = agent.initialize_session(scenario.starting_context)

        metadata = RunMetadata(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            category=scenario.category,
            risk_level=scenario.risk_level,
            agent_version=agent_version,
            started_at=started_at,
            perturbations_enabled=self.enable_perturbations,
        )

        transcript: list[TurnRecord] = []
        tool_events_all: list[ToolEvent] = []
        error: str | None = None

        try:
            for step in scenario.conversation_steps:
                user_input = step.user

                # Apply perturbations if enabled
                applied_perturbations: list[str] = []
                if self.enable_perturbations and step.perturbations:
                    user_input, applied_perturbations = apply_perturbations(
                        user_input, step.perturbations
                    )

                # Mock latency injection
                if self.inject_mock_latency:
                    latency_ms = mock_latency(60, 350)
                else:
                    latency_ms = 0

                # Send turn to agent
                with measure_ms() as timing:
                    agent_response = agent.send_user_turn(
                        user_input=user_input,
                        session_state=session_state,
                        tool_simulation=step.tool_simulation,
                    )

                actual_latency = timing.get("elapsed_ms", latency_ms)
                session_state = agent.get_session_state()
                tool_calls = agent.get_tool_calls()
                tool_event_dicts = agent.get_tool_events()

                # Build TurnRecord
                turn_record = TurnRecord(
                    turn=step.turn,
                    user_input=user_input,
                    agent_response=agent_response,
                    tool_calls_made=tool_calls,
                    tool_results=[e.get("output", {}) for e in tool_event_dicts],
                    latency_ms=actual_latency,
                    perturbations_applied=applied_perturbations,
                )
                transcript.append(turn_record)

                # Build ToolEvent records
                for evt in tool_event_dicts:
                    tool_events_all.append(ToolEvent(
                        turn=step.turn,
                        tool_name=evt.get("tool_name", "unknown"),
                        inputs=evt.get("inputs", {}),
                        output=evt.get("output", {}),
                        success=evt.get("success", True),
                        latency_ms=actual_latency,
                        error=evt.get("error"),
                        behavior_simulated=evt.get("behavior_simulated", "normal"),
                    ))

        except Exception as exc:
            error = str(exc)

        completed_at = datetime.utcnow().isoformat()
        total_latency = sum(t.latency_ms for t in transcript)
        metadata.completed_at = completed_at
        metadata.total_turns = len(transcript)
        metadata.total_latency_ms = total_latency
        metadata.status = "error" if error else "completed"

        result = AgentRunResult(
            agent_version=agent_version,
            scenario_id=scenario.scenario_id,
            metadata=metadata,
            transcript=transcript,
            tool_events=tool_events_all,
            session_state=session_state,
            error=error,
        )

        # Persist artifacts
        self._write_artifacts(result, run_id)
        return result

    def _write_artifacts(self, result: AgentRunResult, run_id: str) -> None:
        base = self.runs_dir / run_id / result.scenario_id / result.agent_version
        base.mkdir(parents=True, exist_ok=True)

        save_json(result.metadata.model_dump(), base / "metadata.json")
        save_json([t.model_dump() for t in result.transcript], base / "transcript.json")
        save_json([e.model_dump() for e in result.tool_events], base / "tool_events.json")
        save_json(result.session_state, base / "session_state.json")
        if result.error:
            save_json({"error": result.error}, base / "error.json")
