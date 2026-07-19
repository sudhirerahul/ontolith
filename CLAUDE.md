# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CallGuard AI — a pre-deployment validation gate for Voice AI agents. It runs an agent through adversarial test scenarios, compares it against a baseline, scores every response (LLM judge + deterministic trip-wires), and issues a **PASS / WARN / BLOCK** release verdict.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e .
```

No API keys are required for local development — the default mode uses mock agents and a deterministic evaluator fallback.

## Commands

Run via the installed `callguard` console script or `python -m callguard_ai` (needs `PYTHONPATH=src` if not installed with `pip install -e .`).

```bash
# Full run, all static scenarios, no API keys needed (mock agents)
python -m callguard_ai run --all

# Single scenario / one category
python -m callguard_ai run --scenario SEC_001
python -m callguard_ai run --category security

# With voice perturbations (text-level ASR-error simulation)
python -m callguard_ai run --all --perturbations

# LLM-backed agents (needs OPENROUTER_API_KEY) instead of mocks
python -m callguard_ai run --all --llm

# Test a real Azure AI Foundry deployment as the candidate
# (needs AZURE_OPENAI_ENDPOINT/AZURE_FOUNDRY_PROJECT_ENDPOINT, AZURE_FOUNDRY_KEY, AZURE_FOUNDRY_MODEL)
python -m callguard_ai run --all --foundry

# Add fresh LLM-generated adversarial scenarios each run (needs OPENROUTER_API_KEY)
python -m callguard_ai run --all --dynamic
python -m callguard_ai run --all --dynamic-only          # fastest demo: 1 dynamic case/category, no static
python -m callguard_ai run --all --dynamic --dynamic-count 3 --dynamic-categories security compliance

# Regenerate the HTML report for a past run
python -m callguard_ai report --latest
python -m callguard_ai report --run <run_id>

# Interactive dashboard
python -m callguard_ai dashboard
# or directly:
streamlit run src/callguard_ai/reporting/streamlit_app.py

# List all static scenarios
python -m callguard_ai list

# Print setup instructions (OpenRouter + Azure Foundry key acquisition)
python -m callguard_ai setup
```

### Retail extensions

```bash
# Retail Roleplay Studio — turn a retailer playbook into scenarios
python -m callguard_ai studio generate --retailer "Ashley HomeStore" \
  --playbook samples/retail/ashley_homestore_playbook.txt \
  --catalog samples/retail/catalog.json \
  --methodology samples/retail/methodology.txt \
  --objections samples/retail/objections.txt \
  --brand-tone samples/retail/brand_tone.txt \
  --count 100
python -m callguard_ai studio list --retailer "Ashley HomeStore"

# Run the generated scenarios against the retail sales-associate mock agents
python -m callguard_ai run --category retail_sales --retail

# Prompt Debugger — root-cause card for any failed/low-scoring scenario in a run
python -m callguard_ai debug show --run <run_id> --scenario <scenario_id>

# Golden dataset — real customer transcript → reviewed → permanent regression test
python -m callguard_ai golden import --transcript samples/retail/sample_customer_transcript.json --retailer "Ashley HomeStore"
python -m callguard_ai golden list --status pending
python -m callguard_ai golden approve <scenario_id>
python -m callguard_ai golden reject <scenario_id> --reason "..."
```

### Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/test_evaluators.py -v          # single file
python -m pytest tests/test_evaluators.py::test_name -v   # single test
```

`tests/conftest.py` inserts `src/` onto `sys.path`, so tests import `callguard_ai` without needing the package installed.

## Architecture

Pipeline: **Batch Runner → (agents × scenarios) → Evaluation Engine → Release Gate → Report**.

1. **Scenarios** (`scenarios/<category>/*.yaml`, parsed into `models/scenario.py::Scenario`) — hand-authored adversarial conversations across 5 categories: `security`, `compliance`, `regression`, `voice_robustness`, `reliability`. Note some YAML files hold multiple scenario IDs (e.g. `SEC_001_004.yaml` has SEC_001-004). `scenarios/dynamic_generator.py` can generate additional scenarios at runtime via an LLM, reading the candidate's live system prompt (from `agent_definition.yaml` or `AZURE_FOUNDRY_SYSTEM_PROMPT`) so generated attacks target the agent's actual configured rules.

2. **Agents** (`agents/`) — every agent implements the `BaseAgentAdapter` protocol (`base.py`): `initialize_session`, `send_user_turn`, `get_tool_calls`, `get_tool_events`, `get_session_state`, `get_version`. This is what lets the runner swap in any backend without touching evaluation code.
   - Two adapters are built per run: **baseline** (known-good reference) and **candidate** (agent under test) — `agents/adapters.py::BaselineAgentAdapter` / `CandidateAgentAdapter`.
   - Mode selection is env-var driven, not just CLI flags: `USE_LLM_AGENT=true` + `OPENROUTER_API_KEY` switches both adapters from `MockAgentCore` to `LLMAgentCore`. The candidate LLM agent intentionally uses a weakened system prompt (`FLAWED_AGENT_SYSTEM_PROMPT` in `adapters.py`) to simulate a real prompt regression.
   - `--foundry` swaps the candidate for `FoundryAgentAdapter` (`foundry_agent.py`), which calls a real Azure OpenAI/Foundry deployment; baseline stays mock/OpenRouter.
   - `mock_agent.py` is deterministic and rule-based (`introduce_flaws=True` for the candidate reproduces known failure modes like PII leaks) — this is what makes the whole pipeline runnable with zero API keys.

3. **Scenario/Batch Runner** (`runner/scenario_runner.py`, `runner/batch_runner.py`) — `BatchRunner.run_all()` loads scenarios, builds the baseline/candidate pair via `_build_agents()`, runs both through every scenario turn-by-turn, and diffs transcripts/tool calls (`utils/diffing.py`) between baseline and candidate.

4. **Evaluation** (`evaluators/engine.py::evaluate`) — orchestrates independent sub-evaluators per scenario result, each returning a scored dimension:
   - `regression_eval.py` → task success, context retention, interruption recovery
   - `security_eval.py` → security score + PII/bypass detection (LLM judge with deterministic trip-wire fallback)
   - `compliance_eval.py` → compliance score + missed-escalation detection
   - `reliability_eval.py` → tool correctness + latency
   - `taxonomy.py` → classifies failures into a fixed 16-code taxonomy (`TAXONOMY` dict), each with a severity (`critical`/`high`/`medium`)
   - Dimension weights live in `config/scoring.yaml` (must sum to 100) and are applied in `engine.py` to produce `overall_score`, plus composite `risk_score` and `stability_score`.

5. **Release Gate** (`gate/release_gate.py`) — evaluates ordered rules from `config/release_gate.yaml` against the evaluation results (BLOCK rules for critical security/PII/verification-bypass/emergency-miss, WARN rules for regressions/repetition/tool errors) plus score-floor rules, producing a `ReleaseVerdict` (PASS/WARN/BLOCK) with structured reasons.

6. **Output** — `reporting/html_report.py` renders a self-contained HTML report (Jinja2) per run into `reports/`; raw JSON artifacts (per-scenario `comparison.json`, `verdict.json`) go to `runs/<run_id>/`. `reporting/streamlit_app.py` is a dashboard that reads from `runs/` to browse historical runs.

7. **Retail extensions** — a parallel `category="retail_sales"` path that reuses the pipeline above end-to-end (same `Scenario` YAML format, same recursive loader, same runner):
   - **Roleplay Studio** (`playbook/`) — `parsers.py` ingests a playbook (PDF/txt) + catalog (JSON/CSV); `roleplay_generator.py::RoleplayStudio` turns them into persona × objection-tree `Scenario`s (deterministic template, or LLM-enhanced when `OPENROUTER_API_KEY` is set), written to `scenarios/retail/<retailer_slug>/`. `agents/retail_mock_agent.py` + `agents/retail_adapters.py` (used via `run --retail`) simulate a good associate (discovers before resolving) vs. a flawed one (resolves immediately) — the concrete regression the other two features reason about.
   - **Prompt Debugger** (`analysis/transcript_debugger.py`) — for any failing/low-scoring candidate evaluation, produces a structured `RootCauseAnalysis` (concern → response → missed opportunity → expected behavior → likely prompt issue → suggested change → regression tests affected), saved as `runs/<run_id>/<scenario_id>/root_cause.json`. Viewable via `debug show` or the dashboard's Prompt Debugger tab.
   - **Golden dataset** (`golden/`) — `transcript_intake.py` replays a real customer transcript through the same `evaluate()`/`analyze_transcript()` path to draft a permanent regression `Scenario`; `registry.py::GoldenRegistry` tracks pending → approved → verified state in `golden_dataset/registry.json`. Approving moves the YAML into `scenarios/golden/<retailer_slug>/`, so it's automatically included in every future run — `BatchRunner` marks it `verified` once it passes, or demotes it back to `approved` if it regresses.
   - `evaluators/engine.py` branches on `scenario.category == "retail_sales"` to a different dimension set (`evaluators/sales_eval.py`: discovery + objection_resolution, reusing `regression_eval`/`reliability_eval` for the rest) instead of the healthcare-oriented security/compliance evaluators.
   - `dashboard/trends.py` aggregates historical runs into quality trends per sales dimension for the Streamlit dashboard's Retail Quality tab.

### Key config files (not code, but drive behavior)

- `config/scoring.yaml` — dimension weights, grade thresholds, risk multipliers
- `config/release_gate.yaml` — ordered verdict rules and score-floor rules
- `config/perturbations.yaml` — voice/ASR-error text mutation configuration (used by `perturbations/text_mutators.py` and `event_injectors.py`)

### Gotcha

Local imports inside a function that shadow a module-level import of the same name make Python treat the name as local for the *entire* function (`UnboundLocalError` on the other branches) — this bit `BatchRunner._build_agents()` once already (fixed). Watch for the same pattern before adding new conditional imports inside existing functions.
