"""
vendor_setup_validation.py

Standardized vendor setup validation -- the structured control that replaced
ad hoc, per-entity vendor onboarding. Run against the migrated vendor master
(data/target/vendors.csv + vendor_entity_crosswalk.csv), it catches the
setup defects that used to surface later as payment delays or misdirected
funds: missing tax IDs, payment terms outside policy, and vendors whose
active/inactive status disagrees across entities.

Usage:
    python automation/vendor_setup_validation.py
Produces:
    automation/vendor_validation_report.csv
    prints a pass/fail summary to the console
"""

import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(ROOT, "data", "target")
REPORT_PATH = os.path.join(ROOT, "automation", "vendor_validation_report.csv")

MAX_ALLOWED_TERMS_DAYS = 45
TRUE_VALUES = {"y", "yes", "1"}
FALSE_VALUES = {"n", "no", "0"}


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def normalize_flag(raw):
    v = (raw or "").strip().lower()
    if v in TRUE_VALUES:
        return True
    if v in FALSE_VALUES:
        return False
    return None  # missing/unrecognized


def validate():
    vendors = load_csv(os.path.join(TARGET_DIR, "vendors.csv"))
    crosswalk = load_csv(os.path.join(TARGET_DIR, "vendor_entity_crosswalk.csv"))

    by_vendor = {}
    for row in crosswalk:
        by_vendor.setdefault(row["vendor_id"], []).append(row)

    issues = []
    for v in vendors:
        vid = v["vendor_id"]
        entity_rows = by_vendor.get(vid, [])

        if not v.get("tax_id"):
            issues.append((vid, v["vendor_name"], "MISSING_TAX_ID",
                            "No tax ID on file -- required before first payment run."))

        terms = int(v["standard_terms_days"])
        if terms > MAX_ALLOWED_TERMS_DAYS:
            issues.append((vid, v["vendor_name"], "TERMS_OUTSIDE_POLICY",
                            f"Payment terms of {terms} days exceed the {MAX_ALLOWED_TERMS_DAYS}-day policy ceiling."))

        flags = [normalize_flag(r["legacy_active_flag"]) for r in entity_rows]
        distinct_flags = {f for f in flags if f is not None}
        if len(distinct_flags) > 1:
            entities = ", ".join(r["entity"] for r in entity_rows)
            issues.append((vid, v["vendor_name"], "CONFLICTING_ACTIVE_STATUS",
                            f"Active status disagrees across entities ({entities}) -- resolve before payment."))
        if any(f is None for f in flags):
            issues.append((vid, v["vendor_name"], "MISSING_ACTIVE_FLAG",
                            "One or more entities never recorded an active/inactive status."))

    with open(REPORT_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vendor_id", "vendor_name", "issue_code", "detail"])
        w.writerows(issues)

    total_vendors = len(vendors)
    flagged_vendors = len({row[0] for row in issues})
    print(f"Validated {total_vendors} vendors")
    print(f"{flagged_vendors} vendor(s) flagged, {len(issues)} total issue(s)")
    print(f"Report written to {REPORT_PATH}")
    return issues


if __name__ == "__main__":
    validate()
