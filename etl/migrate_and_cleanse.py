"""
migrate_and_cleanse.py

The migration itself: reads the three entities' inconsistent legacy CSVs
from data/legacy/, resolves each vendor to a single canonical record,
standardizes dates/currency/terms, flags duplicate invoice entries, and
loads everything into a SQLite database built from sql/schema.sql.

It also writes clean, unified CSVs to data/target/ so the migrated data is
readable directly on GitHub without needing to open the database.

Usage:
    python etl/migrate_and_cleanse.py
Produces:
    erp_case_study.db          (gitignored -- rebuild locally any time)
    data/target/vendors.csv
    data/target/vendor_entity_crosswalk.csv
    data/target/invoices.csv
    data/target/bank_transactions.csv
"""

import csv
import os
import re
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_DIR = os.path.join(ROOT, "data", "legacy")
TARGET_DIR = os.path.join(ROOT, "data", "target")
SCHEMA_PATH = os.path.join(ROOT, "sql", "schema.sql")
DB_PATH = os.path.join(ROOT, "erp_case_study.db")

ENTITIES = [
    ("Meridian North", "MN"),
    ("Meridian West", "MW"),
    ("Meridian Coastal", "MC"),
]

DATE_FORMATS = {
    "MN": "%Y-%m-%d",
    "MW": "%m/%d/%Y",
    "MC": "%d-%b-%Y",
}


def parse_date(raw, code):
    if not raw:
        return None
    return datetime.strptime(raw.strip(), DATE_FORMATS[code]).date().isoformat()


def parse_amount(raw):
    if raw is None or raw == "":
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    return round(float(cleaned), 2)


def normalize_terms(raw):
    """'Net 30' / '30 days' / 'N30' -> 30"""
    digits = re.findall(r"\d+", raw or "")
    return int(digits[0]) if digits else 30


def normalize_vendor_name(raw):
    """Collapse whitespace/casing differences so the same real vendor,
    entered three different ways across three spreadsheets, resolves to one
    canonical name."""
    cleaned = re.sub(r"\s+", " ", (raw or "").strip())
    return cleaned.title().replace("Hvac", "HVAC").replace("It ", "IT ")


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def build_database():
    os.makedirs(TARGET_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    cur = conn.cursor()

    # --- entities ---
    entity_id_by_code = {}
    for name, code in ENTITIES:
        cur.execute("INSERT INTO entities (entity_name, entity_code) VALUES (?, ?)", (name, code))
        entity_id_by_code[code] = cur.lastrowid

    # --- vendors: resolve duplicates across entities into one canonical row ---
    vendor_id_by_canonical_name = {}
    vendor_terms = {}
    crosswalk_rows = []  # for data/target/vendor_entity_crosswalk.csv

    for name, code in ENTITIES:
        rows = load_csv(os.path.join(LEGACY_DIR, f"vendors_{code.lower()}.csv"))
        for row in rows:
            canon = normalize_vendor_name(row["vendor_name"])
            terms_days = normalize_terms(row["payment_terms"])
            tax_id = row.get("tax_id", "") or None

            if canon not in vendor_id_by_canonical_name:
                cur.execute(
                    "INSERT INTO vendors (vendor_name, category, standard_terms_days, tax_id) VALUES (?, ?, ?, ?)",
                    (canon, row.get("category", ""), terms_days, tax_id),
                )
                vendor_id_by_canonical_name[canon] = cur.lastrowid
                vendor_terms[canon] = terms_days
            elif tax_id and not vendor_terms.get(f"__taxid__{canon}"):
                # backfill a missing tax_id from a later, more complete legacy row
                cur.execute(
                    "UPDATE vendors SET tax_id = COALESCE(tax_id, ?) WHERE vendor_id = ?",
                    (tax_id, vendor_id_by_canonical_name[canon]),
                )
                vendor_terms[f"__taxid__{canon}"] = True

            vendor_id = vendor_id_by_canonical_name[canon]
            active_raw = (row.get("active") or "").strip()
            cur.execute(
                "INSERT INTO vendor_entity_ids (vendor_id, entity_id, legacy_vendor_id, legacy_active_flag) "
                "VALUES (?, ?, ?, ?)",
                (vendor_id, entity_id_by_code[code], row["vendor_id"], active_raw),
            )
            crosswalk_rows.append({
                "vendor_id": vendor_id,
                "vendor_name": canon,
                "entity": name,
                "legacy_vendor_id": row["vendor_id"],
                "legacy_active_flag": active_raw,
            })

    # --- invoices, with legacy-vendor-id -> canonical-vendor-id lookup per entity ---
    legacy_to_canonical = {}  # (entity_code, legacy_vendor_id) -> vendor_id
    cur.execute(
        "SELECT vei.entity_id, e.entity_code, vei.legacy_vendor_id, vei.vendor_id "
        "FROM vendor_entity_ids vei JOIN entities e ON e.entity_id = vei.entity_id"
    )
    for entity_id, code, legacy_id, vendor_id in cur.fetchall():
        legacy_to_canonical[(code, legacy_id)] = vendor_id

    seen_signatures = set()  # (entity, vendor_id, amount, invoice_date) -> duplicate detection
    invoice_target_rows = []

    for name, code in ENTITIES:
        rows = load_csv(os.path.join(LEGACY_DIR, f"invoices_{code.lower()}.csv"))
        for row in rows:
            vendor_id = legacy_to_canonical[(code, row["vendor_id"])]
            invoice_date = parse_date(row["invoice_date"], code)
            due_date = parse_date(row["due_date"], code)
            paid_date = parse_date(row["paid_date"], code) if row.get("paid_date") else None
            amount = parse_amount(row["amount"])

            signature = (code, vendor_id, amount, invoice_date)
            is_duplicate = 1 if signature in seen_signatures else 0
            seen_signatures.add(signature)

            cur.execute(
                "INSERT INTO invoices (invoice_id, entity_id, vendor_id, invoice_date, due_date, "
                "paid_date, amount, status, po_reference, is_duplicate) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    row["invoice_id"], entity_id_by_code[code], vendor_id, invoice_date, due_date,
                    paid_date, amount, row["status"], row.get("po_reference") or None, is_duplicate,
                ),
            )
            invoice_target_rows.append({
                "invoice_id": row["invoice_id"], "entity": name, "vendor_id": vendor_id,
                "invoice_date": invoice_date, "due_date": due_date, "paid_date": paid_date or "",
                "amount": amount, "status": row["status"], "po_reference": row.get("po_reference") or "",
                "is_duplicate": is_duplicate,
            })

    # --- bank transactions ---
    bank_target_rows = []
    for name, code in ENTITIES:
        rows = load_csv(os.path.join(LEGACY_DIR, f"bank_transactions_{code.lower()}.csv"))
        for row in rows:
            tx_date = parse_date(row["transaction_date"], code)
            amount = parse_amount(row["amount"])
            matched = row.get("matched_invoice_id") or None
            cur.execute(
                "INSERT INTO bank_transactions (transaction_id, entity_id, matched_invoice_id, "
                "transaction_date, amount) VALUES (?,?,?,?,?)",
                (row["transaction_id"], entity_id_by_code[code], matched, tx_date, amount),
            )
            bank_target_rows.append({
                "transaction_id": row["transaction_id"], "entity": name,
                "matched_invoice_id": matched or "", "transaction_date": tx_date, "amount": amount,
            })

    conn.commit()

    # --- write clean target CSVs for human/GitHub browsing ---
    cur.execute("SELECT vendor_id, vendor_name, category, standard_terms_days, tax_id FROM vendors ORDER BY vendor_id")
    with open(os.path.join(TARGET_DIR, "vendors.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vendor_id", "vendor_name", "category", "standard_terms_days", "tax_id"])
        w.writerows(cur.fetchall())

    with open(os.path.join(TARGET_DIR, "vendor_entity_crosswalk.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["vendor_id", "vendor_name", "entity", "legacy_vendor_id", "legacy_active_flag"])
        w.writeheader()
        w.writerows(crosswalk_rows)

    with open(os.path.join(TARGET_DIR, "invoices.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(invoice_target_rows[0].keys()))
        w.writeheader()
        w.writerows(invoice_target_rows)

    with open(os.path.join(TARGET_DIR, "bank_transactions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(bank_target_rows[0].keys()))
        w.writeheader()
        w.writerows(bank_target_rows)

    n_vendors = len(vendor_id_by_canonical_name)
    n_legacy_vendor_rows = len(crosswalk_rows)
    print(f"Resolved {n_legacy_vendor_rows} legacy vendor rows into {n_vendors} canonical vendors "
          f"({n_legacy_vendor_rows - n_vendors} duplicate cross-entity entries eliminated)")
    print(f"Loaded {len(invoice_target_rows)} invoices ({sum(r['is_duplicate'] for r in invoice_target_rows)} flagged as duplicate entries)")
    print(f"Loaded {len(bank_target_rows)} bank transactions")
    print(f"Database written to {DB_PATH}")
    print(f"Clean CSVs written to {TARGET_DIR}")

    conn.close()


if __name__ == "__main__":
    build_database()
