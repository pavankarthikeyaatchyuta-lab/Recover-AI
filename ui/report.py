"""
report.py — Step 10 of RecoverAI

Generates a standalone, professional merchant summary HTML report
using Jinja2 and inline CSS.
"""

import json
import os
import sys
from datetime import datetime, timezone
from jinja2 import Template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)

from baseline.naive_retry import run_baseline
from agent.stopping_rules import evaluate
from agent.executor import _simulate_outcome
from evaluation.counterfactual import compare
from core.metrics import compute
from core import audit


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RecoverAI Recovery Report</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #1f2937;
      background-color: #f9fafb;
      margin: 0;
      padding: 32px 16px;
      line-height: 1.5;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 32px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    header {
      border-bottom: 2px solid #3b82f6;
      padding-bottom: 16px;
      margin-bottom: 28px;
    }
    h1 {
      margin: 0;
      color: #111827;
      font-size: 24px;
      font-weight: 700;
    }
    .subtitle {
      color: #6b7280;
      font-size: 14px;
      margin-top: 4px;
    }
    h2 {
      font-size: 18px;
      color: #1f2937;
      margin-top: 32px;
      margin-bottom: 12px;
      border-left: 4px solid #3b82f6;
      padding-left: 10px;
    }
    .grid-metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 16px;
    }
    .card-label {
      font-size: 12px;
      color: #64748b;
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .card-val {
      font-size: 22px;
      font-weight: 700;
      color: #0f172a;
      margin-top: 6px;
    }
    .card-sub {
      font-size: 12px;
      color: #10b981;
      margin-top: 4px;
      font-weight: 500;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      font-size: 14px;
    }
    th, td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid #e5e7eb;
    }
    th {
      background-color: #f8fafc;
      color: #475569;
      font-weight: 600;
      font-size: 13px;
    }
    tr:hover {
      background-color: #f1f5f9;
    }
    .badge {
      display: inline-block;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 600;
    }
    .badge-green {
      background-color: #d1fae5;
      color: #065f46;
    }
    .badge-amber {
      background-color: #fef3c7;
      color: #92400e;
    }
    .badge-blue {
      background-color: #dbeafe;
      color: #1e40af;
    }
    footer {
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid #e5e7eb;
      text-align: center;
      color: #9ca3af;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>RecoverAI Recovery Report</h1>
      <div class="subtitle">Generated on {{ report_date }} | Autonomous Subscription Revenue Recovery</div>
    </header>

    <!-- Section 1: Top Metrics -->
    <h2>Summary Metrics</h2>
    <div class="grid-metrics">
      <div class="card">
        <div class="card-label">Recovery Rate</div>
        <div class="card-val">{{ "%.1f"|format(metrics.recovery_rate * 100) }}%</div>
        <div class="card-sub">{{ "+%.1f"|format(metrics.recovery_lift * 100) }}% vs Baseline</div>
      </div>
      <div class="card">
        <div class="card-label">Revenue Recovered</div>
        <div class="card-val">₹{{ "{:,}".format(metrics.revenue_recovered) }}</div>
        <div class="card-sub">₹{{ "{:,}".format(metrics.incremental_revenue) }} Incremental</div>
      </div>
      <div class="card">
        <div class="card-label">Recovery Lift</div>
        <div class="card-val">+{{ summary.recovery_lift }} Subs</div>
        <div class="card-sub">Baseline: {{ summary.baseline_recovered }}</div>
      </div>
      <div class="card">
        <div class="card-label">Actions Avoided</div>
        <div class="card-val">{{ summary.baseline_unnecessary_actions - summary.recoverai_unnecessary_actions }}</div>
        <div class="card-sub">{{ summary.recoverai_unnecessary_actions }} total wasted</div>
      </div>
    </div>

    <!-- Section 2: By Failure Code -->
    <h2>Recovery by Failure Code</h2>
    <table>
      <thead>
        <tr>
          <th>Failure Code</th>
          <th>Total Cases</th>
          <th>RecoverAI Recovered</th>
          <th>Recovery Rate</th>
        </tr>
      </thead>
      <tbody>
        {% for code, stats in metrics.by_failure_code.items() %}
        <tr>
          <td><strong>{{ code }}</strong></td>
          <td>{{ stats.total }}</td>
          <td>{{ stats.recovered }}</td>
          <td><span class="badge badge-blue">{{ "%.1f"|format(stats.rate * 100) }}%</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <!-- Section 3: Top RECOVERAI_WON Cases -->
    <h2>Top 5 RecoverAI Recovery Wins</h2>
    <table>
      <thead>
        <tr>
          <th>Subscription ID</th>
          <th>Amount</th>
          <th>Agent Action</th>
          <th>Rationale</th>
        </tr>
      </thead>
      <tbody>
        {% for item in top_wins %}
        <tr>
          <td><code>{{ item.subscription_id }}</code></td>
          <td><strong>₹{{ item.amount }}</strong></td>
          <td><span class="badge badge-green">{{ item.recoverai.action }}</span></td>
          <td>{{ item.recoverai.rationale }}</td>
        </tr>
        {% else %}
        <tr>
          <td colspan="4" style="color: #6b7280; text-align: center;">No specific wins recorded</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <!-- Section 4: Escalated Cases -->
    <h2>Cases Escalated for Merchant Review ({{ escalated_cases|length }})</h2>
    <table>
      <thead>
        <tr>
          <th>Subscription ID</th>
          <th>Amount</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for item in escalated_cases %}
        <tr>
          <td><code>{{ item.subscription_id }}</code></td>
          <td>₹{{ item.amount }}</td>
          <td><span class="badge badge-amber">{{ item.reason }}</span></td>
        </tr>
        {% else %}
        <tr>
          <td colspan="3" style="color: #6b7280; text-align: center;">No cases escalated</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <footer>
      Generated by RecoverAI &bull; Track 03: AI Revenue Recovery &bull; Razorpay AI Buildathon 2026
    </footer>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def generate_report(
    output_path: str = os.path.join(ROOT_DIR, "reports", "recovery_report.html")
) -> str:
    """Generate the static merchant summary HTML report."""
    data_dir = os.path.join(ROOT_DIR, "data")
    with open(os.path.join(data_dir, "subscriptions.json"), "r", encoding="utf-8") as f:
        subscriptions = json.load(f)
    with open(os.path.join(data_dir, "outcome_model.json"), "r", encoding="utf-8") as f:
        outcome_model = json.load(f)

    # 1. Baseline
    baseline = run_baseline(subscriptions, outcome_model)

    # 2. RecoverAI
    action_map = {
        "INSUFFICIENT_FUNDS": "PAYDAY_RETRY",
        "CARD_EXPIRED": "PAYMENT_LINK",
        "MANDATE_REVOKED": "PAYMENT_LINK",
        "NETWORK_ERROR": "IMMEDIATE_RETRY",
        "UPI_TIMEOUT": "IMMEDIATE_RETRY",
    }

    recoverai_results = []
    escalated_cases = []

    for sub in subscriptions:
        sub_id = sub["subscription_id"]
        stopping = evaluate(sub)
        fc = sub["failure_code"]
        tier = sub["tier"]
        amount = sub["amount"]

        if stopping.triggered:
            if stopping.disposition == "ESCALATED":
                escalated_cases.append({
                    "subscription_id": sub_id,
                    "amount": amount,
                    "reason": stopping.reason or "High risk / mandate revoked intent signal",
                })
            recoverai_results.append({
                "subscription_id": sub_id,
                "amount": amount,
                "failure_code": fc,
                "tier": tier,
                "action": "DO_NOT_ACT",
                "timing_days": 0,
                "outcome": "NO_ACTION",
                "disposition": stopping.disposition,
                "rationale": stopping.reason,
            })
            continue

        act = action_map.get(fc, "PAYDAY_RETRY")
        outcome, _ = _simulate_outcome(act, fc, tier, sub_id)
        timing = 1 if act == "IMMEDIATE_RETRY" else (3 if act == "PAYDAY_RETRY" else 2)

        recoverai_results.append({
            "subscription_id": sub_id,
            "amount": amount,
            "failure_code": fc,
            "tier": tier,
            "action": act,
            "timing_days": timing,
            "outcome": outcome,
            "attempts": 1,
            "rationale": f"Intelligent {act} tailored for {fc}",
        })

    # 3. Compare & Metrics
    cf_data = compare(recoverai_results, baseline["per_subscription"])
    all_events = []
    for sub in subscriptions:
        all_events.extend(audit.get_events(sub["subscription_id"]))
    metrics = compute(recoverai_results, baseline, all_events)

    # 4. Top 5 wins
    wins = [r for r in cf_data["per_subscription"] if r["delta"] == "RECOVERAI_WON"]
    wins.sort(key=lambda x: x["amount"], reverse=True)
    top_wins = wins[:5]

    # 5. Render HTML
    template = Template(HTML_TEMPLATE)
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    rendered_html = template.render(
        report_date=now_str,
        metrics=metrics,
        summary=cf_data["summary"],
        top_wins=top_wins,
        escalated_cases=escalated_cases,
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    return output_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    report_file = os.path.join(ROOT_DIR, "reports", "recovery_report.html")
    out = generate_report(report_file)
    print(f"Merchant recovery report generated successfully: {out}")
