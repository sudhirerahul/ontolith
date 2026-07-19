"""
HTML Report Generator — produces a polished, self-contained release report.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from jinja2 import Template

from ..models.verdict import ReleaseVerdict
from ..utils.io import ensure_dir

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CallGuard AI — Release Report {{ run_id }}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg: #0a0c10;
    --surface: #12151c;
    --surface2: #1a1e28;
    --border: #22283a;
    --text: #c9d1e0;
    --muted: #5a6480;
    --accent: #00d4ff;
    --pass: #00e676;
    --warn: #ffb300;
    --block: #ff1744;
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Syne', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
  }

  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 32px 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .header-left h1 {
    font-size: 28px;
    font-weight: 800;
    color: var(--accent);
    letter-spacing: -0.5px;
  }

  .header-left .subtitle {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 12px;
    margin-top: 4px;
  }

  .verdict-badge {
    font-size: 32px;
    font-weight: 800;
    padding: 12px 32px;
    border-radius: 8px;
    font-family: var(--mono);
    letter-spacing: 2px;
  }

  .verdict-PASS  { background: rgba(0,230,118,0.15); color: var(--pass); border: 2px solid var(--pass); }
  .verdict-WARN  { background: rgba(255,179,0,0.15); color: var(--warn); border: 2px solid var(--warn); }
  .verdict-BLOCK { background: rgba(255,23,68,0.15); color: var(--block); border: 2px solid var(--block); }

  .container { max-width: 1200px; margin: 0 auto; padding: 40px 48px; }

  .scores-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 40px;
  }

  .score-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    text-align: center;
  }

  .score-card .label {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }

  .score-card .value {
    font-size: 36px;
    font-weight: 800;
    color: var(--accent);
    font-family: var(--mono);
  }

  .section {
    margin-bottom: 40px;
  }

  .section-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    background: var(--surface);
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border);
  }

  th {
    background: var(--surface2);
    color: var(--muted);
    font-family: var(--mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 12px 16px;
    text-align: left;
  }

  td {
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 13px;
  }

  tr:hover td { background: var(--surface2); }

  .tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-family: var(--mono);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .tag-pass  { background: rgba(0,230,118,0.15); color: var(--pass); }
  .tag-fail  { background: rgba(255,23,68,0.15); color: var(--block); }
  .tag-warn  { background: rgba(255,179,0,0.15); color: var(--warn); }
  .tag-block { background: rgba(255,23,68,0.15); color: var(--block); }

  .findings-list {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px 24px;
    list-style: none;
  }

  .findings-list li {
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 13px;
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .findings-list li:last-child { border-bottom: none; }

  .findings-list li::before {
    content: '▸';
    color: var(--accent);
    flex-shrink: 0;
  }

  .taxonomy-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
  }

  .taxonomy-item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .taxonomy-item .code {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text);
  }

  .taxonomy-item .count {
    font-family: var(--mono);
    font-weight: 700;
    font-size: 18px;
    color: var(--warn);
  }

  .run-meta {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    display: flex;
    gap: 32px;
  }

  .empty-state {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 13px;
    padding: 16px;
    text-align: center;
  }

  .delta-pos { color: var(--pass); }
  .delta-neg { color: var(--block); }
  .delta-neu { color: var(--muted); }

  .reason-card {
    background: var(--surface);
    border-left: 3px solid var(--block);
    border-radius: 0 8px 8px 0;
    padding: 14px 18px;
    margin-bottom: 10px;
    font-family: var(--mono);
    font-size: 13px;
  }

  .reason-card.warn { border-left-color: var(--warn); }

  .reason-card .rule-id {
    color: var(--muted);
    font-size: 11px;
    margin-bottom: 4px;
  }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>🛡 CallGuard AI</h1>
    <div class="subtitle">Release Validation Report · Run {{ run_id }} · {{ generated_at }}</div>
  </div>
  <div class="verdict-badge verdict-{{ verdict.verdict }}">{{ verdict.verdict }}</div>
</div>

<div class="container">

  <!-- Score cards -->
  <div class="scores-grid" style="margin-top: 32px;">
    <div class="score-card">
      <div class="label">Overall Score</div>
      <div class="value">{{ "%.1f"|format(verdict.overall_score) }}</div>
    </div>
    <div class="score-card">
      <div class="label">Security Score</div>
      <div class="value" style="color: {% if verdict.security_score >= 80 %}var(--pass){% elif verdict.security_score >= 60 %}var(--warn){% else %}var(--block){% endif %}">{{ "%.1f"|format(verdict.security_score) }}</div>
    </div>
    <div class="score-card">
      <div class="label">Compliance Score</div>
      <div class="value" style="color: {% if verdict.compliance_score >= 80 %}var(--pass){% elif verdict.compliance_score >= 60 %}var(--warn){% else %}var(--block){% endif %}">{{ "%.1f"|format(verdict.compliance_score) }}</div>
    </div>
    <div class="score-card">
      <div class="label">Stability Score</div>
      <div class="value">{{ "%.1f"|format(verdict.stability_score) }}</div>
    </div>
  </div>

  <!-- Scenario summary -->
  <div class="section">
    <div class="section-title">📋 Scenario Summary</div>
    <table>
      <thead>
        <tr>
          <th>Scenario</th>
          <th>Baseline</th>
          <th>Candidate</th>
          <th>Delta</th>
          <th>Status</th>
          <th>Contribution</th>
        </tr>
      </thead>
      <tbody>
        {% for c in comparisons %}
        <tr>
          <td>{{ c.scenario_id }}</td>
          <td>{{ "%.1f"|format(c.baseline_score) }}</td>
          <td>{{ "%.1f"|format(c.candidate_score) }}</td>
          <td class="{% if c.score_delta > 0 %}delta-pos{% elif c.score_delta < 0 %}delta-neg{% else %}delta-neu{% endif %}">
            {{ "%+.1f"|format(c.score_delta) }}
          </td>
          <td>
            {% if c.candidate_passed %}
              <span class="tag tag-pass">PASS</span>
            {% else %}
              <span class="tag tag-fail">FAIL</span>
            {% endif %}
          </td>
          <td>
            {% if c.verdict_contribution == "block" %}
              <span class="tag tag-block">BLOCK</span>
            {% elif c.verdict_contribution == "warn" %}
              <span class="tag tag-warn">WARN</span>
            {% else %}
              <span style="color: var(--muted);">—</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Block / Warn reasons -->
  {% if verdict.block_reasons %}
  <div class="section">
    <div class="section-title">🚫 Block Reasons</div>
    {% for r in verdict.block_reasons %}
    <div class="reason-card">
      <div class="rule-id">{{ r.rule_id }}</div>
      <div>{{ r.description }}</div>
      {% if r.scenario_ids %}
      <div style="color: var(--muted); margin-top: 4px;">Scenarios: {{ r.scenario_ids | join(", ") }}</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if verdict.warn_reasons %}
  <div class="section">
    <div class="section-title">⚠ Warn Reasons</div>
    {% for r in verdict.warn_reasons %}
    <div class="reason-card warn">
      <div class="rule-id">{{ r.rule_id }}</div>
      <div>{{ r.description }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Security findings -->
  {% if verdict.security_findings %}
  <div class="section">
    <div class="section-title">🔒 Security Findings</div>
    <ul class="findings-list">
      {% for f in verdict.security_findings %}
      <li>{{ f }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <!-- Compliance findings -->
  {% if verdict.compliance_findings %}
  <div class="section">
    <div class="section-title">📜 Compliance Findings</div>
    <ul class="findings-list">
      {% for f in verdict.compliance_findings %}
      <li>{{ f }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <!-- Reliability findings -->
  {% if verdict.reliability_findings %}
  <div class="section">
    <div class="section-title">⚙ Reliability Findings</div>
    <ul class="findings-list">
      {% for f in verdict.reliability_findings %}
      <li>{{ f }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <!-- Top regressions -->
  {% if verdict.top_regressions %}
  <div class="section">
    <div class="section-title">📉 Top Regressions</div>
    <ul class="findings-list">
      {% for r in verdict.top_regressions %}
      <li>{{ r }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <!-- Failure taxonomy -->
  {% if verdict.failure_taxonomy_counts %}
  <div class="section">
    <div class="section-title">🏷 Failure Taxonomy</div>
    <div class="taxonomy-grid">
      {% for code, count in verdict.failure_taxonomy_counts.items() | sort(attribute='1', reverse=True) %}
      <div class="taxonomy-item">
        <span class="code">{{ code }}</span>
        <span class="count">{{ count }}</span>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <div class="run-meta">
    <span>Run ID: {{ run_id }}</span>
    <span>Generated: {{ generated_at }}</span>
    <span>Scenarios: {{ verdict.total_scenarios }}</span>
    <span>Passed: {{ verdict.passed }} / Failed: {{ verdict.failed }}</span>
  </div>

</div>
</body>
</html>
"""


def generate_html_report(
    verdict: ReleaseVerdict,
    comparisons: list,
    reports_dir: Path,
) -> Path:
    ensure_dir(reports_dir)
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html = Template(HTML_TEMPLATE).render(
        verdict=verdict,
        comparisons=comparisons,
        run_id=verdict.run_id,
        generated_at=generated_at,
    )

    out_path = reports_dir / f"report_{verdict.run_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
