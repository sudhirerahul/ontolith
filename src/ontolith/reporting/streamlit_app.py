"""
Ontolith — Streamlit Dashboard
Run with: streamlit run src/ontolith/reporting/streamlit_app.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# Allow running from project root
def _find_project_root() -> Path:
    """Walk up AND check cwd — works however Streamlit is launched."""
    # First check current working directory directly
    cwd = Path.cwd()
    if (cwd / "runs").exists() and (cwd / "scenarios").exists():
        return cwd

    # Then walk up from this file
    candidate = Path(__file__).resolve()
    for _ in range(8):
        candidate = candidate.parent
        if (candidate / "runs").exists() and (candidate / "scenarios").exists():
            return candidate

    # Last resort — walk up from cwd
    candidate = cwd
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "runs").exists() and (candidate / "scenarios").exists():
            return candidate

    return cwd
PROJECT_ROOT = _find_project_root()
import streamlit as st

st.set_page_config(
    page_title="Ontolith",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', system-ui, sans-serif;
}

[data-testid="stMetricValue"] {
    font-family: 'Roboto', system-ui, sans-serif;
    font-variant-numeric: tabular-nums;
}

section[data-testid="stSidebar"] h2 {
    color: #d55181;
}

.verdict-banner {
    font-family: 'Roboto', system-ui, sans-serif;
    font-size: 48px;
    font-weight: 700;
    text-align: center;
    padding: 24px;
    border-radius: 12px;
    letter-spacing: 4px;
    margin-bottom: 24px;
    font-variant-numeric: tabular-nums;
}
.banner-PASS  { background: rgba(12,163,12,0.1); color: #0ca30c; border: 2px solid #0ca30c; }
.banner-WARN  { background: rgba(250,178,25,0.1); color: #fab219; border: 2px solid #fab219; }
.banner-BLOCK { background: rgba(208,59,59,0.1); color: #d03b3b; border: 2px solid #d03b3b; }

.metric-card {
    background: #1a1a19;
    border: 1px solid #2c2c2a;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)


RUNS_DIR = PROJECT_ROOT / "runs"


def load_run(run_id: str) -> dict | None:
    verdict_path = RUNS_DIR / run_id / "verdict.json"
    if verdict_path.exists():
        return json.loads(verdict_path.read_text())
    return None


def load_comparisons(run_id: str) -> list[dict]:
    comps = []
    run_dir = RUNS_DIR / run_id
    for scenario_dir in run_dir.iterdir():
        if scenario_dir.is_dir():
            comp_file = scenario_dir / "comparison.json"
            if comp_file.exists():
                comps.append(json.loads(comp_file.read_text()))
    return comps


def load_eval(run_id: str, scenario_id: str, agent: str) -> dict | None:
    f = RUNS_DIR / run_id / scenario_id / f"{agent}_eval.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


def get_available_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        [d.name for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "verdict.json").exists()],
        reverse=True,
    )


# ---- Sidebar ----
st.sidebar.markdown("## Ontolith")
st.sidebar.markdown("*Release Validation Gate*")
st.sidebar.divider()

runs = get_available_runs()
if not runs:
    st.sidebar.warning("No completed runs found.")
    st.title("Ontolith")
    st.info("No runs found. Run: `python -m ontolith run --all` first.")
    st.stop()

selected_run = st.sidebar.selectbox("Select Run", runs, index=0)
verdict_data = load_run(selected_run)
if not verdict_data:
    st.error("Could not load verdict for this run.")
    st.stop()

comparisons = load_comparisons(selected_run)

# ---- Main content ----
verdict_str = verdict_data.get("verdict", "PASS")
st.markdown(
    f'<div class="verdict-banner banner-{verdict_str}">{verdict_str}</div>',
    unsafe_allow_html=True,
)

# Score metrics
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Overall Score", f"{verdict_data.get('overall_score', 0):.1f}")
with col2:
    st.metric("Security", f"{verdict_data.get('security_score', 0):.1f}")
with col3:
    st.metric("Compliance", f"{verdict_data.get('compliance_score', 0):.1f}")
with col4:
    st.metric("Stability", f"{verdict_data.get('stability_score', 0):.1f}")
with col5:
    st.metric(
        "Scenarios",
        f"{verdict_data.get('passed', 0)}/{verdict_data.get('total_scenarios', 0)} passed",
    )

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Scenarios", "Security", "Compliance", "Reliability", "Taxonomy",
    "Retail Quality", "Roleplay Studio", "Prompt Debugger",
])

with tab1:
    st.subheader("Baseline vs Candidate Comparison")
    if comparisons:
        import pandas as pd
        rows = []
        for c in comparisons:
            rows.append({
                "Scenario": c["scenario_id"],
                "Baseline": c["baseline_score"],
                "Candidate": c["candidate_score"],
                "Delta": c["score_delta"],
                "Passed": "Pass" if c["candidate_passed"] else "Fail",
                "Contribution": c.get("verdict_contribution", "neutral").upper(),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Regressions
        regressions = [c for c in comparisons if c["score_delta"] < 0]
        if regressions:
            st.subheader("Regressions")
            for r in sorted(regressions, key=lambda x: x["score_delta"]):
                st.error(f"**{r['scenario_id']}**: {r['score_delta']:+.1f} pts | New failures: {r.get('new_failures', [])}")
    else:
        st.info("No comparison data found for this run.")

with tab2:
    st.subheader("Security Findings")
    findings = verdict_data.get("security_findings", [])
    if findings:
        for f in findings:
            st.error(f)
    else:
        st.success("No security violations detected.")

    block_reasons = verdict_data.get("block_reasons", [])
    security_blocks = [r for r in block_reasons if "SEC" in r.get("rule_id", "") or "PII" in r.get("rule_id", "") or "VERIFICATION" in r.get("rule_id", "")]
    if security_blocks:
        st.subheader("Block Triggers")
        for r in security_blocks:
            st.error(f"**{r['rule_id']}**: {r['description']}")

with tab3:
    st.subheader("Compliance Findings")
    findings = verdict_data.get("compliance_findings", [])
    if findings:
        for f in findings:
            st.warning(f)
    else:
        st.success("No compliance violations detected.")

with tab4:
    st.subheader("Reliability Findings")
    findings = verdict_data.get("reliability_findings", [])
    if findings:
        for f in findings:
            st.warning(f)
    else:
        st.success("No reliability issues detected.")

    top_regressions = verdict_data.get("top_regressions", [])
    if top_regressions:
        st.subheader("Top Score Regressions")
        for r in top_regressions:
            st.info(r)

with tab5:
    st.subheader("Failure Taxonomy")
    taxonomy = verdict_data.get("failure_taxonomy_counts", {})
    if taxonomy:
        import pandas as pd
        rows = [{"Failure Code": k, "Occurrences": v} for k, v in
                sorted(taxonomy.items(), key=lambda x: -x[1])]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.bar_chart(data={k: v for k, v in taxonomy.items()})
    else:
        st.success("No failures recorded in taxonomy.")


def _discover_retailers() -> dict[str, str]:
    """slug -> display name, from scenarios/retail/*/_roleplay_set.json and scenarios/golden/*/"""
    names: dict[str, str] = {}
    for base in ["retail", "golden"]:
        base_dir = PROJECT_ROOT / "scenarios" / base
        if not base_dir.exists():
            continue
        for d in base_dir.iterdir():
            if not d.is_dir():
                continue
            rs_path = d / "_roleplay_set.json"
            if rs_path.exists():
                names[d.name] = json.loads(rs_path.read_text()).get("retailer", d.name.replace("_", " ").title())
            else:
                names.setdefault(d.name, d.name.replace("_", " ").title())
    return names


with tab6:
    st.subheader("Retail Quality Dashboard")
    from ontolith.dashboard.trends import compute_quality_trends
    from ontolith.golden.registry import GoldenRegistry

    retailers = _discover_retailers()
    if not retailers:
        st.info("No retail data yet. Generate scenarios with `ontolith studio generate` "
                 "and run them with `run --category retail_sales --retail`.")
    else:
        retailer_slug = st.selectbox("Retailer", list(retailers.keys()),
                                      format_func=lambda s: retailers[s], key="retail_dash_retailer")
        trends = compute_quality_trends(PROJECT_ROOT, retailer=retailers[retailer_slug])

        st.markdown("#### Quality Trend")
        series = trends["dimension_series"]
        if series:
            import pandas as pd
            all_runs = sorted({run_id for pts in series.values() for run_id, _ in pts})
            chart_df = pd.DataFrame(index=all_runs)
            for dim, pts in series.items():
                col = {run_id: score for run_id, score in pts}
                chart_df[dim] = [col.get(r) for r in all_runs]
            st.line_chart(chart_df)

            deltas = trends["trend_deltas"]
            cols = st.columns(min(len(deltas), 5) or 1)
            for i, (dim, delta) in enumerate(deltas.items()):
                with cols[i % len(cols)]:
                    st.metric(dim.replace("_", " ").title(), f"{delta:+.1f} pts" if len(series[dim]) >= 2 else "—")
        else:
            st.info("No retail run history yet for this retailer.")

        st.markdown("#### Top Failures")
        if trends["top_failures"]:
            import pandas as pd
            st.dataframe(pd.DataFrame(trends["top_failures"], columns=["Failure Code", "Count"]),
                         use_container_width=True, hide_index=True)
        else:
            st.success("No failures recorded yet.")

        st.markdown("#### Recent Customer Issues")
        registry = GoldenRegistry(PROJECT_ROOT)
        entries = [e for e in registry.list() if e["retailer"] == retailers[retailer_slug]]
        status_icon = {"pending": "Pending Review", "approved": "Added to regression suite",
                       "verified": "Verified", "rejected": "Rejected"}
        if entries:
            for e in entries:
                st.markdown(f"- **{e['customer_issue_id']}** ({e['scenario_id']}) — "
                             f"{status_icon.get(e['status'], e['status'])} — {e.get('root_cause_summary', '')}")
        else:
            st.info("No customer issues imported yet. Use `ontolith golden import`.")

        pending = registry.list(status="pending")
        pending = [e for e in pending if e["retailer"] == retailers[retailer_slug]]
        if pending:
            st.markdown("#### Pending Review")
            for e in pending:
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.markdown(f"**{e['scenario_id']}** — {e.get('root_cause_summary', '')}")
                if c2.button("Approve", key=f"approve_{e['scenario_id']}"):
                    registry.approve(e["scenario_id"])
                    st.rerun()
                if c3.button("Reject", key=f"reject_{e['scenario_id']}"):
                    registry.reject(e["scenario_id"], reason="Rejected via dashboard")
                    st.rerun()

with tab7:
    st.subheader("Retail Roleplay Studio")
    retail_only = {
        d.name: json.loads((d / "_roleplay_set.json").read_text()).get("retailer", d.name)
        for d in (PROJECT_ROOT / "scenarios" / "retail").iterdir()
        if d.is_dir() and (d / "_roleplay_set.json").exists()
    } if (PROJECT_ROOT / "scenarios" / "retail").exists() else {}

    if not retail_only:
        st.info("No roleplay sets yet. Generate one with `ontolith studio generate --retailer ... --playbook ...`.")
    else:
        slug = st.selectbox("Retailer", list(retail_only.keys()),
                             format_func=lambda s: retail_only[s], key="studio_retailer")
        rs = json.loads((PROJECT_ROOT / "scenarios" / "retail" / slug / "_roleplay_set.json").read_text())

        st.caption(f"{'LLM-enhanced' if rs['llm_powered'] else 'Template-generated'} · "
                   f"{rs['metadata']['scenario_count']} scenarios")

        st.markdown("#### Product / Objection Tree")
        for node in rs["hierarchy"]["nodes"]:
            st.markdown(f"- **{node['label']}** — {len(node['scenario_ids'])} scenario(s)")

        st.markdown("#### Personas")
        import pandas as pd
        st.dataframe(pd.DataFrame([
            {"Persona": p["name"], "Motivation": p["motivation"], "Tone": p["tone"],
             "Budget sensitivity": p["budget_sensitivity"], "Objections": ", ".join(p["objections"])}
            for p in rs["personas"]
        ]), use_container_width=True, hide_index=True)

with tab8:
    st.subheader("Prompt Debugger — Root Cause Analysis")
    run_dir = RUNS_DIR / selected_run
    root_cause_files = sorted(run_dir.glob("*/root_cause.json")) if run_dir.exists() else []

    if not root_cause_files:
        st.info("No root-cause analyses in this run (only generated for scenarios that failed "
                 "or scored below 70).")
    else:
        options = {f.parent.name: f for f in root_cause_files}
        scenario_id = st.selectbox("Scenario", list(options.keys()), key="debugger_scenario")
        rc = json.loads(options[scenario_id].read_text())

        mode = "LLM-powered" if rc.get("llm_powered") else "Deterministic fallback"
        st.caption(mode)

        st.markdown(f"**Conversation Summary**\n\n{rc.get('conversation_summary', '')}")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Customer Concern**\n\n{rc.get('customer_concern', '')}")
        c2.markdown(f"**Associate Response**\n\n{rc.get('associate_response', '')}")
        st.error(f"**Missed Opportunity**\n\n{rc.get('missed_opportunity', '')}")
        st.markdown("**Expected Behavior**")
        for i, step in enumerate(rc.get("expected_behavior", [])):
            st.markdown(f"{i+1}. {step}")
        st.warning(f"**Likely Prompt Issue**\n\n{rc.get('likely_prompt_issue', '')}")
        st.success(f"**Suggested Prompt Change**\n\n{rc.get('suggested_prompt_change', '')}")
        if rc.get("regression_tests_affected"):
            st.markdown("**Regression Tests Affected**")
            for sid in rc["regression_tests_affected"]:
                st.markdown(f"- `{sid}`")

# Block/Warn reasons in sidebar
if verdict_data.get("block_reasons"):
    st.sidebar.error("BLOCK Reasons")
    for r in verdict_data["block_reasons"]:
        st.sidebar.markdown(f"- {r['description']}")

if verdict_data.get("warn_reasons"):
    st.sidebar.warning("WARN Reasons")
    for r in verdict_data["warn_reasons"]:
        st.sidebar.markdown(f"- {r['description']}")

st.sidebar.divider()
st.sidebar.caption(f"Run: `{selected_run}`")
