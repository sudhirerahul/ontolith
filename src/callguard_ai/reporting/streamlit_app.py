"""
CallGuard AI — Streamlit Dashboard
Run with: streamlit run src/callguard_ai/reporting/streamlit_app.py
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
    page_title="CallGuard AI",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@700;800&display=swap');

.verdict-banner {
    font-family: 'JetBrains Mono', monospace;
    font-size: 48px;
    font-weight: 700;
    text-align: center;
    padding: 24px;
    border-radius: 12px;
    letter-spacing: 4px;
    margin-bottom: 24px;
}
.banner-PASS  { background: rgba(0,230,118,0.1); color: #00e676; border: 2px solid #00e676; }
.banner-WARN  { background: rgba(255,179,0,0.1); color: #ffb300; border: 2px solid #ffb300; }
.banner-BLOCK { background: rgba(255,23,68,0.1); color: #ff1744; border: 2px solid #ff1744; }

.metric-card {
    background: #12151c;
    border: 1px solid #22283a;
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
st.sidebar.markdown("## 🛡 CallGuard AI")
st.sidebar.markdown("*Release Validation Gate*")
st.sidebar.divider()

runs = get_available_runs()
if not runs:
    st.sidebar.warning("No completed runs found.")
    st.title("🛡 CallGuard AI")
    st.info("No runs found. Run: `python -m callguard_ai run --all` first.")
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

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Scenarios", "🔒 Security", "📜 Compliance", "⚙ Reliability", "🏷 Taxonomy"
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
                "Passed": "✅" if c["candidate_passed"] else "❌",
                "Contribution": c.get("verdict_contribution", "neutral").upper(),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Regressions
        regressions = [c for c in comparisons if c["score_delta"] < 0]
        if regressions:
            st.subheader("⬇ Regressions")
            for r in sorted(regressions, key=lambda x: x["score_delta"]):
                st.error(f"**{r['scenario_id']}**: {r['score_delta']:+.1f} pts | New failures: {r.get('new_failures', [])}")
    else:
        st.info("No comparison data found for this run.")

with tab2:
    st.subheader("Security Findings")
    findings = verdict_data.get("security_findings", [])
    if findings:
        for f in findings:
            st.error(f"🔴 {f}")
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
            st.warning(f"⚠ {f}")
    else:
        st.success("No compliance violations detected.")

with tab4:
    st.subheader("Reliability Findings")
    findings = verdict_data.get("reliability_findings", [])
    if findings:
        for f in findings:
            st.warning(f"⚙ {f}")
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

# Block/Warn reasons in sidebar
if verdict_data.get("block_reasons"):
    st.sidebar.error("🚫 BLOCK Reasons")
    for r in verdict_data["block_reasons"]:
        st.sidebar.markdown(f"- {r['description']}")

if verdict_data.get("warn_reasons"):
    st.sidebar.warning("⚠ WARN Reasons")
    for r in verdict_data["warn_reasons"]:
        st.sidebar.markdown(f"- {r['description']}")

st.sidebar.divider()
st.sidebar.caption(f"Run: `{selected_run}`")
