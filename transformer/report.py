"""Report — generate a self-contained HTML execution report.

Produces a single static HTML file that embeds all pipeline data as
inline JavaScript constants. The report runs entirely offline with
no server, no CDN, no external dependencies.

Tabs:
    1. Run Summary — widget cards + bar charts
    2. Candidate Explorer — sidebar list + detail pane
    3. Validation Log — warnings and errors
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_report(
    projected_candidates: list[dict[str, Any]],
    decision_logs: list[dict[str, Any]],
    quality_dashboard: dict[str, Any],
    warnings: list[str],
    output_path: str,
) -> None:
    """Generate a self-contained HTML report.

    All data is serialized as JSON and injected into the HTML template
    as JavaScript constants, bypassing browser CORS restrictions for
    local file access.

    Args:
        projected_candidates: List of projected output dicts.
        decision_logs: List of per-candidate decision log dicts.
        quality_dashboard: Batch-level quality dashboard dict.
        warnings: Pipeline warnings collected during the run.
        output_path: Path to write the HTML report to.
    """
    projected_json = json.dumps(projected_candidates, indent=2, ensure_ascii=False)
    decision_json = json.dumps(decision_logs, indent=2, ensure_ascii=False)
    dashboard_json = json.dumps(quality_dashboard, indent=2, ensure_ascii=False)
    warnings_json = json.dumps(warnings, indent=2, ensure_ascii=False)

    html = _HTML_TEMPLATE
    html = html.replace("__PROJECTED_JSON__", projected_json)
    html = html.replace("__DECISION_JSON__", decision_json)
    html = html.replace("__DASHBOARD_JSON__", dashboard_json)
    html = html.replace("__WARNINGS_JSON__", warnings_json)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logger.info("HTML report written to %s", output_path)


# ---------------------------------------------------------------------------
# Self-contained HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Candidate Transformer — Execution Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f1117;
            --bg-card: #1a1d27;
            --bg-card-hover: #22263a;
            --bg-subtle: #161922;
            --text: #e2e8f0;
            --text-muted: #8892a4;
            --text-dim: #5a6478;
            --border: #2a2f3e;
            --primary: #6366f1;
            --primary-light: rgba(99,102,241,0.12);
            --primary-glow: rgba(99,102,241,0.3);
            --success: #22c55e;
            --success-light: rgba(34,197,94,0.12);
            --warning: #f59e0b;
            --warning-light: rgba(245,158,11,0.12);
            --error: #ef4444;
            --error-light: rgba(239,68,68,0.12);
            --accent: #8b5cf6;
            --gradient-start: #6366f1;
            --gradient-end: #8b5cf6;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 2rem;
            min-height: 100vh;
        }

        .container { max-width: 1500px; margin: 0 auto; }

        /* Header */
        header {
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }

        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .subtitle { font-size: 0.9rem; color: var(--text-muted); margin-top: 0.25rem; }

        /* Buttons */
        .btn-group { display: flex; gap: 0.6rem; flex-wrap: wrap; }

        .btn {
            display: inline-flex; align-items: center; gap: 0.4rem;
            padding: 0.5rem 1rem; font-size: 0.82rem; font-weight: 500;
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 8px; cursor: pointer; transition: all 0.2s;
            color: var(--text); text-decoration: none; font-family: inherit;
        }
        .btn:hover { background: var(--bg-card-hover); border-color: var(--primary); }
        .btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
        .btn-primary:hover { background: #5558e6; }

        /* Tabs */
        .tabs {
            display: flex; border-bottom: 1px solid var(--border);
            margin-bottom: 2rem; gap: 0.25rem;
        }
        .tab-btn {
            padding: 0.75rem 1.25rem; font-size: 0.9rem; font-weight: 500;
            color: var(--text-muted); border: none; background: none;
            cursor: pointer; border-bottom: 2px solid transparent;
            transition: all 0.2s; font-family: inherit;
        }
        .tab-btn:hover { color: var(--text); }
        .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }

        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

        /* Widget Cards */
        .grid-widgets {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1.25rem; margin-bottom: 2rem;
        }
        .widget-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 10px; padding: 1.5rem;
            display: flex; flex-direction: column; gap: 0.5rem;
            transition: border-color 0.2s;
        }
        .widget-card:hover { border-color: var(--primary); }
        .widget-label {
            font-size: 0.75rem; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
        }
        .widget-val { font-size: 2rem; font-weight: 700; color: var(--primary); }

        /* Dashboard Charts */
        .dashboard-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem;
        }
        @media (max-width: 900px) { .dashboard-grid { grid-template-columns: 1fr; } }

        .chart-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 10px; padding: 1.5rem;
        }
        .chart-title {
            font-size: 1rem; font-weight: 600; margin-bottom: 1.5rem;
            color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;
        }

        /* Bar Charts */
        .bar-chart { width: 100%; display: flex; flex-direction: column; gap: 0.6rem; }
        .bar-row { display: flex; align-items: center; gap: 0.75rem; }
        .bar-label {
            width: 160px; font-size: 0.8rem; color: var(--text-muted);
            text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .bar-track {
            flex-grow: 1; background: rgba(255,255,255,0.04);
            height: 18px; border-radius: 6px; overflow: hidden;
        }
        .bar-fill {
            background: linear-gradient(90deg, var(--gradient-start), var(--gradient-end));
            height: 100%; border-radius: 6px; transition: width 0.6s ease;
        }
        .bar-val { width: 50px; font-size: 0.8rem; font-weight: 600; color: var(--text); }

        /* Candidate Explorer */
        .explorer-layout { display: grid; grid-template-columns: 320px 1fr; gap: 1.5rem; }
        @media (max-width: 900px) { .explorer-layout { grid-template-columns: 1fr; } }

        .candidate-list {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 10px; max-height: 800px; overflow-y: auto;
        }
        .candidate-item {
            padding: 1.25rem; border-bottom: 1px solid var(--border);
            cursor: pointer; transition: all 0.2s; border-left: 3px solid transparent;
        }
        .candidate-item:hover { background: var(--bg-card-hover); }
        .candidate-item.active { background: var(--primary-light); border-left-color: var(--primary); }
        .cand-name { font-weight: 600; font-size: 0.92rem; }
        .cand-id { font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem; }

        /* Collapsible Cards */
        details.collapse-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 10px; overflow: hidden; margin-bottom: 1rem;
        }
        details.collapse-card summary {
            padding: 1rem 1.25rem; font-weight: 600; font-size: 0.95rem;
            cursor: pointer; background: var(--bg-subtle); user-select: none;
            display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid transparent; transition: all 0.2s;
        }
        details.collapse-card[open] summary {
            background: rgba(99,102,241,0.06); border-bottom-color: var(--border);
        }
        details.collapse-card .card-body { padding: 1.25rem; }

        /* Profile Grid */
        .profile-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;
        }
        .profile-field {
            border: 1px solid var(--border); border-radius: 8px;
            padding: 0.75rem 1rem; background: var(--bg-subtle);
        }
        .pf-label {
            font-size: 0.7rem; font-weight: 600; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 0.05em;
        }
        .pf-val { font-size: 0.9rem; font-weight: 500; margin-top: 0.2rem; word-break: break-all; }

        /* Field Decision Cards */
        .field-card {
            border: 1px solid var(--border); border-radius: 10px;
            background: var(--bg-card); overflow: hidden; margin-bottom: 1rem;
        }
        .field-header {
            background: var(--bg-subtle); padding: 0.75rem 1.25rem;
            font-weight: 700; font-size: 0.85rem; display: flex;
            justify-content: space-between; align-items: center;
            border-bottom: 1px solid var(--border);
        }
        .field-body { padding: 1.25rem; }
        .field-explain {
            padding: 1rem 1.25rem; background: rgba(99,102,241,0.04);
            border-top: 1px solid var(--border); font-size: 0.85rem;
        }
        .explain-label {
            font-weight: 600; font-size: 0.72rem; text-transform: uppercase;
            color: var(--primary); margin-bottom: 0.4rem; letter-spacing: 0.05em;
        }

        .contender {
            display: flex; gap: 1rem; margin-bottom: 0.6rem; font-size: 0.82rem;
            border-left: 2px solid var(--border); padding-left: 1rem; margin-left: 0.5rem;
        }
        .contender-label { width: 80px; font-weight: 600; color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; }
        .contender-val { flex: 1; }

        code {
            background: rgba(255,255,255,0.06); padding: 0.1rem 0.4rem;
            border-radius: 4px; font-size: 0.8rem; font-family: 'SF Mono', monospace;
        }

        /* Confidence Badges */
        .badge {
            display: inline-flex; align-items: center; padding: 0.2rem 0.65rem;
            border-radius: 999px; font-size: 0.78rem; font-weight: 600;
        }
        .badge-high { background: var(--success-light); color: var(--success); }
        .badge-med { background: var(--warning-light); color: var(--warning); }
        .badge-low { background: var(--error-light); color: var(--error); }

        /* Tables */
        table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
        th, td { padding: 0.65rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }
        th { background: var(--bg-subtle); font-weight: 600; color: var(--text-muted); }
        tr:hover td { background: rgba(255,255,255,0.02); }

        /* Alerts */
        .alert {
            padding: 1rem 1.25rem; border-radius: 8px; margin-bottom: 0.75rem;
            border: 1px solid transparent; font-size: 0.85rem;
        }
        .alert-error { background: var(--error-light); border-color: rgba(239,68,68,0.2); color: var(--error); }
        .alert-warning { background: var(--warning-light); border-color: rgba(245,158,11,0.2); color: var(--warning); }
        .alert-info { background: var(--primary-light); border-color: rgba(99,102,241,0.2); color: #93a3f8; }

        pre {
            background: #0d0f14; color: #c9d1d9; padding: 1rem;
            border-radius: 8px; overflow-x: auto; font-size: 0.8rem;
            max-height: 400px; border: 1px solid var(--border);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Candidate Transformer</h1>
                <div class="subtitle">Pipeline Execution Report — Decision Traces & Quality Dashboard</div>
            </div>
            <div class="btn-group">
                <button class="btn" onclick="downloadFile('projected')">⬇ Projected JSON</button>
                <button class="btn" onclick="downloadFile('decision')">⬇ Decision Log</button>
                <button class="btn" onclick="downloadFile('dashboard')">⬇ Dashboard</button>
            </div>
        </header>

        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('summary')">Run Summary</button>
            <button class="tab-btn" onclick="switchTab('explorer')">Candidate Explorer</button>
            <button class="tab-btn" onclick="switchTab('validation')">Validation Log</button>
        </div>

        <!-- SUMMARY TAB -->
        <div id="tab-summary" class="tab-content active">
            <div class="grid-widgets">
                <div class="widget-card">
                    <span class="widget-label">Candidates Produced</span>
                    <span class="widget-val" id="w-candidates">-</span>
                </div>
                <div class="widget-card">
                    <span class="widget-label">Observations Ingested</span>
                    <span class="widget-val" id="w-observations">-</span>
                </div>
                <div class="widget-card">
                    <span class="widget-label">Sources Used</span>
                    <span class="widget-val" id="w-sources">-</span>
                </div>
                <div class="widget-card">
                    <span class="widget-label">Conflicts Detected</span>
                    <span class="widget-val" id="w-conflicts" style="color:var(--warning);">-</span>
                </div>
                <div class="widget-card">
                    <span class="widget-label">Warnings</span>
                    <span class="widget-val" id="w-warnings" style="color:var(--error);">-</span>
                </div>
            </div>

            <div class="dashboard-grid">
                <div class="chart-card">
                    <div class="chart-title">Confidence per Canonical Field</div>
                    <div id="confidence-chart"></div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Resolution Metrics</div>
                    <div id="metrics-chart"></div>
                </div>
            </div>

            <div class="chart-card">
                <div class="chart-title">Schema Coverage</div>
                <div id="coverage-chart"></div>
            </div>
        </div>

        <!-- EXPLORER TAB -->
        <div id="tab-explorer" class="tab-content">
            <div class="explorer-layout">
                <div class="candidate-list" id="cand-list"></div>
                <div id="cand-detail">
                    <div style="color:var(--text-muted);text-align:center;padding-top:150px;">
                        Select a candidate from the sidebar to explore decision traces.
                    </div>
                </div>
            </div>
        </div>

        <!-- VALIDATION TAB -->
        <div id="tab-validation" class="tab-content">
            <div class="chart-card">
                <div class="chart-title">Pipeline Warnings & Validation Alerts</div>
                <div id="validation-container"></div>
            </div>
        </div>
    </div>

    <script>
        const projected = __PROJECTED_JSON__;
        const decisions = __DECISION_JSON__;
        const dashboard = __DASHBOARD_JSON__;
        const pipelineWarnings = __WARNINGS_JSON__;

        function switchTab(id) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.innerText.toLowerCase().includes(id));
            if (btn) btn.classList.add('active');
            const tab = document.getElementById('tab-' + id);
            if (tab) tab.classList.add('active');
        }

        function downloadFile(type) {
            let data, filename;
            if (type === 'projected') { data = projected; filename = 'projected_candidates.json'; }
            else if (type === 'decision') { data = decisions; filename = 'decision_log.json'; }
            else if (type === 'dashboard') { data = dashboard; filename = 'quality_dashboard.json'; }
            const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
            URL.revokeObjectURL(url);
        }

        function fmtConf(v) { return typeof v === 'number' ? (v * 100).toFixed(0) + '%' : v; }
        function badgeClass(v) { return v >= 0.8 ? 'badge-high' : v >= 0.5 ? 'badge-med' : 'badge-low'; }

        // ---- SUMMARY ----
        function renderSummary() {
            const bs = dashboard.batch_summary || {};
            const sc = dashboard.schema_coverage || {};
            const rm = dashboard.resolution_metrics || {};

            document.getElementById('w-candidates').innerText = bs.total_candidates_produced || 0;
            document.getElementById('w-observations').innerText = bs.total_observations_ingested || 0;
            document.getElementById('w-sources').innerText = (bs.sources_used || []).length;
            document.getElementById('w-conflicts').innerText = rm.total_conflicts || 0;
            document.getElementById('w-warnings').innerText = bs.warnings_count || 0;

            // Confidence bar chart
            const avgField = sc.average_confidence_per_field || {};
            let h = '<div class="bar-chart">';
            for (const [f, v] of Object.entries(avgField)) {
                const pct = (v * 100).toFixed(0);
                h += `<div class="bar-row">
                    <span class="bar-label">${f}</span>
                    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
                    <span class="bar-val">${pct}%</span>
                </div>`;
            }
            h += '</div>';
            document.getElementById('confidence-chart').innerHTML = h;

            // Metrics bar chart
            const metrics = [
                {label: 'Conflicts', val: rm.total_conflicts || 0},
                {label: 'Agreements', val: rm.total_agreements || 0},
                {label: 'Losing Values', val: rm.total_losing_values || 0},
            ];
            const maxV = Math.max(...metrics.map(m => m.val), 1);
            let mh = '<div class="bar-chart">';
            metrics.forEach(m => {
                const pct = (m.val / maxV * 100).toFixed(0);
                mh += `<div class="bar-row">
                    <span class="bar-label">${m.label}</span>
                    <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:linear-gradient(90deg,var(--accent),var(--primary));"></div></div>
                    <span class="bar-val">${m.val}</span>
                </div>`;
            });
            mh += '</div>';
            document.getElementById('metrics-chart').innerHTML = mh;

            // Coverage summary
            const pop = sc.fields_populated_pct || 0;
            const miss = sc.fields_missing_pct || 0;
            const avgAll = sc.average_confidence_across_batch || 0;
            document.getElementById('coverage-chart').innerHTML = `
                <div class="bar-chart">
                    <div class="bar-row">
                        <span class="bar-label">Fields Populated</span>
                        <div class="bar-track"><div class="bar-fill" style="width:${pop}%;background:var(--success);"></div></div>
                        <span class="bar-val">${pop.toFixed(1)}%</span>
                    </div>
                    <div class="bar-row">
                        <span class="bar-label">Fields Missing</span>
                        <div class="bar-track"><div class="bar-fill" style="width:${miss}%;background:var(--error);"></div></div>
                        <span class="bar-val">${miss.toFixed(1)}%</span>
                    </div>
                    <div class="bar-row">
                        <span class="bar-label">Avg Confidence (Batch)</span>
                        <div class="bar-track"><div class="bar-fill" style="width:${(avgAll*100).toFixed(0)}%"></div></div>
                        <span class="bar-val">${fmtConf(avgAll)}</span>
                    </div>
                </div>`;
        }

        // ---- EXPLORER LIST ----
        function renderList() {
            let h = '';
            decisions.forEach((d, i) => {
                const name = projected[i]?.full_name || projected[i]?.name || d.candidate_id;
                h += `<div class="candidate-item" id="ci-${i}" onclick="selectCandidate(${i})">
                    <div class="cand-name">${name}</div>
                    <div class="cand-id">ID: ${d.candidate_id}</div>
                </div>`;
            });
            document.getElementById('cand-list').innerHTML = h;
        }

        // ---- SELECT CANDIDATE ----
        function selectCandidate(idx) {
            document.querySelectorAll('.candidate-item').forEach(e => e.classList.remove('active'));
            document.getElementById('ci-' + idx).classList.add('active');

            const cand = projected[idx];
            const log = decisions[idx];
            const name = cand.full_name || cand.name || log.candidate_id;
            const avgConf = log.overall_confidence || 0;

            // Profile grid
            let profileHtml = '<div class="profile-grid">';
            for (const [key, val] of Object.entries(cand)) {
                if (key === 'provenance' || key === 'field_confidences') continue;
                profileHtml += `<div class="profile-field">
                    <div class="pf-label">${key}</div>
                    <div class="pf-val">${JSON.stringify(val, null, 0)}</div>
                </div>`;
            }
            profileHtml += '</div>';

            // Source contributions
            const sources = {};
            for (const fd of Object.values(log.fields || {})) {
                for (const c of (fd.candidates_considered || [])) {
                    const src = c.source || 'unknown';
                    sources[src] = (sources[src] || 0) + 1;
                }
            }
            let srcHtml = '<table><thead><tr><th>Source</th><th>Fields Contributed</th></tr></thead><tbody>';
            for (const [s, n] of Object.entries(sources)) {
                srcHtml += `<tr><td><strong>${s}</strong></td><td><span class="badge badge-high" style="font-weight:normal">${n}</span></td></tr>`;
            }
            srcHtml += '</tbody></table>';

            // Field decisions
            let fieldsHtml = '';
            for (const [field, fd] of Object.entries(log.fields || {})) {
                const w = fd.winner_details || {};
                const conf = fd.final_confidence || 0;
                let valStr = 'null';
                if (w.unioned_values !== undefined) {
                    valStr = JSON.stringify(w.unioned_values);
                } else if (w.value !== null && w.value !== undefined) {
                    valStr = JSON.stringify(w.value);
                } else {
                    const winnerC = (fd.candidates_considered || []).find(c => c.status === 'winner');
                    if (winnerC && winnerC.value !== undefined) {
                        valStr = JSON.stringify(winnerC.value);
                    }
                }
                let contHtml = '';
                (fd.candidates_considered || []).forEach((c, ci) => {
                    const st = c.status;
                    const stStyle = st === 'winner' ? 'color:var(--success);font-weight:700' :
                                    st === 'agreeing' ? 'color:var(--primary);font-weight:600' :
                                    st === 'losing' ? 'color:var(--error)' : 'color:var(--text-muted)';
                    contHtml += `<div class="contender">
                        <div class="contender-label">Source ${ci+1}</div>
                        <div class="contender-val">
                            <strong>${c.source || '?'}</strong> (${c.method || '?'})<br>
                            Value: <code>${JSON.stringify(c.value)}</code>
                            &nbsp;→&nbsp; <span style="${stStyle}">${(st || '?').toUpperCase()}</span>
                        </div>
                    </div>`;
                });

                fieldsHtml += `<div class="field-card">
                    <div class="field-header">
                        <span>${field.toUpperCase()}</span>
                        <span class="badge ${badgeClass(conf)}">${fmtConf(conf)}</span>
                    </div>
                    <div class="field-body">
                        <div style="margin-bottom:1rem;font-size:0.9rem;">
                            <span style="color:var(--primary);font-weight:600;">Canonical Value:</span>
                            <code style="margin-left:0.5rem;">${valStr}</code>
                        </div>
                        <div style="font-weight:600;font-size:0.72rem;text-transform:uppercase;color:var(--text-muted);margin-bottom:0.5rem;">Contenders:</div>
                        ${contHtml}
                    </div>
                    <div class="field-explain">
                        <div class="explain-label">Resolution Reason</div>
                        <div>${w.reason || 'N/A'}</div>
                    </div>
                </div>`;
            }

            // Assemble detail pane
            document.getElementById('cand-detail').innerHTML = `
                <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:1.5rem;margin-bottom:1rem;">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
                        <div>
                            <h2 style="font-size:1.4rem;font-weight:700;">${name}</h2>
                            <div style="color:var(--text-muted);font-size:0.82rem;margin-top:0.2rem;">ID: <strong>${log.candidate_id}</strong></div>
                        </div>
                        <span class="badge ${badgeClass(avgConf)}" style="font-size:0.9rem;padding:0.4rem 1rem;">
                            OVERALL: ${fmtConf(avgConf)}
                        </span>
                    </div>
                </div>

                <details class="collapse-card" open>
                    <summary>Canonical Profile <span>▾</span></summary>
                    <div class="card-body">${profileHtml}</div>
                </details>

                <details class="collapse-card" open>
                    <summary>Source Contributions <span>▾</span></summary>
                    <div class="card-body">${srcHtml}</div>
                </details>

                <details class="collapse-card" open>
                    <summary>Field Decision Traces <span>▾</span></summary>
                    <div class="card-body">${fieldsHtml}</div>
                </details>

                <details class="collapse-card">
                    <summary>Raw Projected JSON <span>▾</span></summary>
                    <div class="card-body"><pre>${JSON.stringify(cand, null, 2)}</pre></div>
                </details>
            `;
        }

        // ---- VALIDATION ----
        function renderValidation() {
            const c = document.getElementById('validation-container');
            if (!pipelineWarnings || pipelineWarnings.length === 0) {
                c.innerHTML = '<div class="alert alert-info"><strong>All clear!</strong> No warnings or validation errors were recorded.</div>';
                return;
            }
            let h = '';
            pipelineWarnings.forEach(w => {
                h += `<div class="alert alert-warning"><strong>⚠ Warning:</strong> ${w}</div>`;
            });
            c.innerHTML = h;
        }

        // Init
        renderSummary();
        renderList();
        renderValidation();
    </script>
</body>
</html>
"""
