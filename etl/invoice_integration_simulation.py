"""
invoice_integration_simulation.py

Simulates the automated invoice/bank-feed integration: runs the exception
queries in sql/reconciliation_queries.sql and the KPI queries in
sql/kpi_queries.sql against the migrated database, writes the results as
CSV reports, and renders the final index.html dashboard at the repo root
by injecting the computed KPI summary straight into dashboard/template.html.
The dashboard is fully self-contained (no fetch, no separate data file) so
it works the moment it's opened -- as a GitHub Pages site or just double-
clicked locally.

Usage:
    python etl/invoice_integration_simulation.py
Requires erp_case_study.db to exist -- run etl/migrate_and_cleanse.py first.

Produces:
    sql/output/unmatched_invoices.csv
    sql/output/unmatched_bank_transactions.csv
    sql/output/amount_variances.csv
    sql/output/backlog_by_month.csv
    sql/output/kpi_before_after.csv
    sql/output/kpi_monthly_trend.csv
    index.html   (repo root -- the live dashboard)
"""

import csv
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "erp_case_study.db")
SQL_DIR = os.path.join(ROOT, "sql")
OUTPUT_DIR = os.path.join(SQL_DIR, "output")
DASHBOARD_TEMPLATE = os.path.join(ROOT, "dashboard", "template.html")
DASHBOARD_OUTPUT = os.path.join(ROOT, "index.html")


def render_dashboard(summary):
    with open(DASHBOARD_TEMPLATE) as f:
        html = f.read()
    payload = json.dumps(summary, indent=2)
    html = html.replace("/*__KPI_DATA_JSON__*/{}/*__END_KPI_DATA_JSON__*/", payload)
    with open(DASHBOARD_OUTPUT, "w") as f:
        f.write(html)


def load_named_queries(path):
    """Split a .sql file on '-- QUERY: <name>' markers into {name: sql}."""
    with open(path) as f:
        text = f.read()
    parts = re.split(r"--\s*QUERY:\s*(\w+)\s*\n", text)
    # parts[0] is the file header/comments before the first marker
    queries = {}
    for i in range(1, len(parts), 2):
        name = parts[i]
        sql = parts[i + 1].strip().rstrip(";")
        queries[name] = sql
    return queries


def rows_to_dicts(cursor, rows):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def write_csv(path, dict_rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not dict_rows:
        with open(path, "w") as f:
            f.write("")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict_rows[0].keys()))
        w.writeheader()
        w.writerows(dict_rows)


def run():
    if not os.path.exists(DB_PATH):
        raise SystemExit("erp_case_study.db not found -- run etl/migrate_and_cleanse.py first.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    recon_queries = load_named_queries(os.path.join(SQL_DIR, "reconciliation_queries.sql"))
    kpi_queries = load_named_queries(os.path.join(SQL_DIR, "kpi_queries.sql"))

    def run_query(sql):
        cur.execute(sql)
        return rows_to_dicts(cur, cur.fetchall())

    unmatched_invoices = run_query(recon_queries["unmatched_invoices"])
    unmatched_bank = run_query(recon_queries["unmatched_bank_transactions"])
    variances = run_query(recon_queries["amount_variances"])
    backlog_by_month = run_query(recon_queries["reconciliation_backlog_by_month"])

    cycle_time = run_query(kpi_queries["reconciliation_cycle_time_before_after"])
    turnaround = run_query(kpi_queries["vendor_payment_turnaround_before_after"])
    error_rate = run_query(kpi_queries["invoice_error_rate_before_after"])
    monthly_trend = run_query(kpi_queries["monthly_kpi_trend"])

    write_csv(os.path.join(OUTPUT_DIR, "unmatched_invoices.csv"), unmatched_invoices)
    write_csv(os.path.join(OUTPUT_DIR, "unmatched_bank_transactions.csv"), unmatched_bank)
    write_csv(os.path.join(OUTPUT_DIR, "amount_variances.csv"), variances)
    write_csv(os.path.join(OUTPUT_DIR, "backlog_by_month.csv"), backlog_by_month)

    kpi_before_after = []
    by_period = {}
    for row in cycle_time:
        by_period.setdefault(row["period"], {})["avg_cycle_time_days"] = row["avg_cycle_time_days"]
    for row in turnaround:
        by_period.setdefault(row["period"], {})["avg_turnaround_days"] = row["avg_turnaround_days"]
    for row in error_rate:
        by_period.setdefault(row["period"], {})["error_rate_pct"] = row["error_rate_pct"]
    for period in ("before", "after"):
        kpi_before_after.append({"period": period, **by_period.get(period, {})})
    write_csv(os.path.join(OUTPUT_DIR, "kpi_before_after.csv"), kpi_before_after)
    write_csv(os.path.join(OUTPUT_DIR, "kpi_monthly_trend.csv"), monthly_trend)

    def pct_change(before, after):
        if not before:
            return None
        return round(100.0 * (before - after) / before, 1)

    before = by_period.get("before", {})
    after = by_period.get("after", {})

    summary = {
        "go_live_date": "2025-07-01",
        "cycle_time": {
            "before_days": before.get("avg_cycle_time_days"),
            "after_days": after.get("avg_cycle_time_days"),
            "pct_improvement": pct_change(before.get("avg_cycle_time_days"), after.get("avg_cycle_time_days")),
        },
        "vendor_turnaround": {
            "before_days": before.get("avg_turnaround_days"),
            "after_days": after.get("avg_turnaround_days"),
            "pct_improvement": pct_change(before.get("avg_turnaround_days"), after.get("avg_turnaround_days")),
        },
        "error_rate": {
            "before_pct": before.get("error_rate_pct"),
            "after_pct": after.get("error_rate_pct"),
            "pct_improvement": pct_change(before.get("error_rate_pct"), after.get("error_rate_pct")),
        },
        "backlog_open_items": len(unmatched_invoices),
        "unmatched_bank_transactions": len(unmatched_bank),
        "amount_variances": len(variances),
        "monthly_trend": monthly_trend,
        "backlog_by_month": backlog_by_month,
    }

    render_dashboard(summary)

    print("Reconciliation & KPI summary")
    print(f"  Cycle time:         {before.get('avg_cycle_time_days')} -> {after.get('avg_cycle_time_days')} days "
          f"({summary['cycle_time']['pct_improvement']}% faster)")
    print(f"  Vendor turnaround:  {before.get('avg_turnaround_days')} -> {after.get('avg_turnaround_days')} days "
          f"({summary['vendor_turnaround']['pct_improvement']}% faster)")
    print(f"  Invoice error rate: {before.get('error_rate_pct')}% -> {after.get('error_rate_pct')}% "
          f"({summary['error_rate']['pct_improvement']}% reduction)")
    print(f"  Open backlog items (unmatched paid invoices): {len(unmatched_invoices)}")
    print(f"  Unmatched bank transactions: {len(unmatched_bank)}")
    print(f"  Amount variances flagged: {len(variances)}")
    print(f"Reports written to {OUTPUT_DIR}")
    print(f"Dashboard rendered to {DASHBOARD_OUTPUT}")

    conn.close()


if __name__ == "__main__":
    run()
