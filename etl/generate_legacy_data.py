"""
Generates the "legacy" source data for the three Meridian Group entities:
inconsistent per-entity spreadsheets for vendors, invoices, and bank
transactions. This is the only place fake data gets invented -- everything
downstream just reads what this script writes, so re-running it from
scratch reproduces the whole repo (python etl/generate_legacy_data.py).

GO_LIVE_DATE (2025-07-01) splits the year into before/after. The
before/after improvement lives in the generation parameters here (slower
turnaround, more errors, worse bank matching pre-go-live) -- the SQL layer
downstream just measures whatever this produces, nothing's hardcoded.

Each entity's files use their own column order, date format, and
terms notation on purpose, and each keeps its own vendor ID numbering even
for vendors shared with the other two -- that's the mess the migration
script has to clean up.
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(42)  # reproducible output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_DIR = os.path.join(ROOT, "data", "legacy")

ENTITIES = ["Meridian North", "Meridian West", "Meridian Coastal"]
ENTITY_CODES = {"Meridian North": "MN", "Meridian West": "MW", "Meridian Coastal": "MC"}

PERIOD_START = date(2025, 1, 1)
GO_LIVE_DATE = date(2025, 7, 1)
PERIOD_END = date(2025, 12, 31)

VENDOR_CATALOG = [
    ("Northgate Facilities Maintenance", "Facilities"),
    ("BrightPath IT Solutions", "IT Services"),
    ("Coastal Office Supply Co.", "Office Supplies"),
    ("Evergreen Landscaping Group", "Landscaping"),
    ("Sentinel Security Services", "Security"),
    ("Clearwater Cleaning Co.", "Janitorial"),
    ("Summit Utilities Consulting", "Utilities"),
    ("Harborline Professional Services", "Professional Services"),
    ("Fraser Valley Electrical", "Facilities"),
    ("Peak Fleet Maintenance", "Fleet"),
    ("Bluepine HVAC Systems", "Facilities"),
    ("Redwood Legal Partners", "Professional Services"),
    ("Cascade Waste Management", "Waste"),
    ("Aldergrove Signage & Print", "Marketing"),
    ("Union Bay Insurance Brokers", "Insurance"),
    ("Nightingale Payroll Services", "Professional Services"),
    ("Silverline Telecom", "IT Services"),
    ("Granite Ridge Contractors", "Facilities"),
]

PAYMENT_TERMS_BY_VENDOR = {name: random.choice([30, 30, 30, 15, 45]) for name, _ in VENDOR_CATALOG}

# Each vendor is used by 1-3 entities; each entity assigns its OWN vendor id
# and formats fields its own way -- this is the "same vendor, three
# spreadsheets" problem the migration has to solve.
VENDOR_ENTITY_MAP = {}
for name, _cat in VENDOR_CATALOG:
    n_entities = random.choice([1, 1, 2, 2, 3])
    VENDOR_ENTITY_MAP[name] = random.sample(ENTITIES, n_entities)

DATE_FORMATS = {
    "Meridian North": "%Y-%m-%d",
    "Meridian West": "%m/%d/%Y",
    "Meridian Coastal": "%d-%b-%Y",
}

TERMS_STYLE = {
    "Meridian North": lambda d: f"Net {d}",
    "Meridian West": lambda d: f"{d} days",
    "Meridian Coastal": lambda d: f"N{d}",
}


def fmt_date(d, entity):
    return d.strftime(DATE_FORMATS[entity])


def daterange_days(start, end):
    return (end - start).days


def random_date(start, end):
    span = daterange_days(start, end)
    return start + timedelta(days=random.randint(0, span))


def build_vendor_rows():
    """Return dict: entity -> list of vendor row dicts (messy, entity-local ids)."""
    entity_vendor_rows = {e: [] for e in ENTITIES}
    entity_counters = {e: 100 for e in ENTITIES}
    vendor_id_lookup = {}  # (entity, vendor_name) -> entity-local vendor id

    for name, category in VENDOR_CATALOG:
        for entity in VENDOR_ENTITY_MAP[name]:
            entity_counters[entity] += 1
            local_id = f"{ENTITY_CODES[entity]}-V{entity_counters[entity]}"
            vendor_id_lookup[(entity, name)] = local_id

            terms_days = PAYMENT_TERMS_BY_VENDOR[name]
            terms_text = TERMS_STYLE[entity](terms_days)

            # Simulate messy legacy quirks
            display_name = name
            if random.random() < 0.15:
                display_name = name.upper()
            if random.random() < 0.1:
                display_name = display_name + "  "  # trailing whitespace

            tax_id = f"BN{random.randint(100000000, 999999999)}RT0001"
            if random.random() < 0.2:
                tax_id = ""  # missing field, common in legacy sheets

            active_flag = random.choice(["Y", "N"]) if entity == "Meridian North" else (
                random.choice(["Yes", "No"]) if entity == "Meridian West" else random.choice(["1", "0"])
            )
            if random.random() < 0.05:
                active_flag = ""

            row = {
                "vendor_id": local_id,
                "vendor_name": display_name,
                "category": category,
                "payment_terms": terms_text,
                "tax_id": tax_id,
                "active": active_flag,
                "entity": entity,
            }
            entity_vendor_rows[entity].append(row)

    return entity_vendor_rows, vendor_id_lookup, entity_counters


def write_vendor_csvs(entity_vendor_rows):
    # Different column order per entity to simulate independently maintained sheets
    col_orders = {
        "Meridian North": ["vendor_id", "vendor_name", "category", "payment_terms", "tax_id", "active"],
        "Meridian West": ["vendor_id", "vendor_name", "payment_terms", "category", "active", "tax_id"],
        "Meridian Coastal": ["vendor_id", "vendor_name", "active", "payment_terms", "tax_id", "category"],
    }
    for entity in ENTITIES:
        fname = os.path.join(LEGACY_DIR, f"vendors_{ENTITY_CODES[entity].lower()}.csv")
        cols = col_orders[entity]
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in entity_vendor_rows[entity]:
                w.writerow({k: row[k] for k in cols})


def gen_invoices_and_bank(entity_vendor_rows, vendor_id_lookup):
    invoice_rows = {e: [] for e in ENTITIES}
    bank_rows = {e: [] for e in ENTITIES}
    inv_counters = {e: 5000 for e in ENTITIES}
    bank_counters = {e: 9000 for e in ENTITIES}

    for entity in ENTITIES:
        vendors_here = entity_vendor_rows[entity]
        n_invoices = random.randint(190, 230)
        for _ in range(n_invoices):
            vendor_row = random.choice(vendors_here)
            vendor_name = vendor_row["vendor_name"].strip()
            terms_days = PAYMENT_TERMS_BY_VENDOR.get(vendor_name.title(), 30)
            # fall back if title-casing broke the lookup due to messy names
            terms_days = PAYMENT_TERMS_BY_VENDOR.get(
                next((n for n, _ in VENDOR_CATALOG if n.lower() == vendor_name.lower()), vendor_name.title()),
                30,
            )

            invoice_date = random_date(PERIOD_START, PERIOD_END - timedelta(days=5))
            before_go_live = invoice_date < GO_LIVE_DATE

            inv_counters[entity] += 1
            invoice_id = f"{ENTITY_CODES[entity]}-INV{inv_counters[entity]}"

            due_date = invoice_date + timedelta(days=terms_days)

            # Turnaround behavior: slow + variable before go-live, fast + tight after
            if before_go_live:
                turnaround = max(1, int(random.gauss(terms_days + 12, 9)))
                po_missing_chance = 0.22
                duplicate_chance = 0.06
            else:
                turnaround = max(1, int(random.gauss(max(terms_days - 20, 3), 3)))
                po_missing_chance = 0.04
                duplicate_chance = 0.01

            paid_date = invoice_date + timedelta(days=turnaround)
            if paid_date > PERIOD_END:
                paid_date = None
            status = "Paid" if paid_date else "Unpaid"

            amount = round(random.uniform(150, 18500), 2)
            po_ref = f"PO-{random.randint(10000,99999)}"
            if random.random() < po_missing_chance:
                po_ref = ""

            amount_str = f"${amount:,.2f}" if entity != "Meridian North" else f"{amount:.2f}"

            row = {
                "invoice_id": invoice_id,
                "vendor_id": vendor_row["vendor_id"],
                "invoice_date": fmt_date(invoice_date, entity),
                "due_date": fmt_date(due_date, entity),
                "paid_date": fmt_date(paid_date, entity) if paid_date else "",
                "amount": amount_str,
                "status": status,
                "po_reference": po_ref,
                "entity": entity,
            }
            invoice_rows[entity].append(row)

            # Duplicate-entry error: legacy double-keying the same invoice
            if random.random() < duplicate_chance:
                dup = dict(row)
                inv_counters[entity] += 1
                dup["invoice_id"] = f"{ENTITY_CODES[entity]}-INV{inv_counters[entity]}"
                invoice_rows[entity].append(dup)

            # Bank transaction side, for reconciliation
            if paid_date:
                if before_go_live:
                    bank_missing_chance = 0.10
                    amount_mismatch_chance = 0.07
                    lag_days = random.choice([0, 0, 1, 2, 5, 9])
                else:
                    bank_missing_chance = 0.02
                    amount_mismatch_chance = 0.01
                    lag_days = random.choice([0, 0, 0, 1, 2])

                if random.random() > bank_missing_chance:
                    bank_counters[entity] += 1
                    bank_amount = amount
                    if random.random() < amount_mismatch_chance:
                        bank_amount = round(amount + random.choice([-25.0, -10.5, 5.25, 18.0]), 2)
                    bank_rows[entity].append({
                        "transaction_id": f"{ENTITY_CODES[entity]}-BANK{bank_counters[entity]}",
                        "matched_invoice_id": invoice_id,
                        "transaction_date": fmt_date(paid_date + timedelta(days=lag_days), entity),
                        "amount": f"{bank_amount:.2f}",
                        "entity": entity,
                    })

        # Unmatched bank transactions with no invoice at all (bank fees, misposted items)
        for _ in range(random.randint(4, 10)):
            bank_counters[entity] += 1
            stray_date = random_date(PERIOD_START, PERIOD_END)
            bank_rows[entity].append({
                "transaction_id": f"{ENTITY_CODES[entity]}-BANK{bank_counters[entity]}",
                "matched_invoice_id": "",
                "transaction_date": fmt_date(stray_date, entity),
                "amount": f"{round(random.uniform(20, 400), 2):.2f}",
                "entity": entity,
            })

    return invoice_rows, bank_rows


def write_invoice_and_bank_csvs(invoice_rows, bank_rows):
    inv_cols = {
        "Meridian North": ["invoice_id", "vendor_id", "invoice_date", "due_date", "paid_date", "amount", "status", "po_reference"],
        "Meridian West": ["invoice_id", "vendor_id", "amount", "invoice_date", "due_date", "paid_date", "status", "po_reference"],
        "Meridian Coastal": ["invoice_id", "vendor_id", "status", "invoice_date", "due_date", "paid_date", "amount", "po_reference"],
    }
    for entity in ENTITIES:
        fname = os.path.join(LEGACY_DIR, f"invoices_{ENTITY_CODES[entity].lower()}.csv")
        cols = inv_cols[entity]
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in invoice_rows[entity]:
                w.writerow({k: row[k] for k in cols})

    bank_cols = ["transaction_id", "matched_invoice_id", "transaction_date", "amount"]
    for entity in ENTITIES:
        fname = os.path.join(LEGACY_DIR, f"bank_transactions_{ENTITY_CODES[entity].lower()}.csv")
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=bank_cols)
            w.writeheader()
            for row in bank_rows[entity]:
                w.writerow({k: row[k] for k in bank_cols})


def main():
    os.makedirs(LEGACY_DIR, exist_ok=True)
    entity_vendor_rows, vendor_id_lookup, _ = build_vendor_rows()
    write_vendor_csvs(entity_vendor_rows)
    invoice_rows, bank_rows = gen_invoices_and_bank(entity_vendor_rows, vendor_id_lookup)
    write_invoice_and_bank_csvs(invoice_rows, bank_rows)

    total_invoices = sum(len(v) for v in invoice_rows.values())
    total_bank = sum(len(v) for v in bank_rows.values())
    total_vendors = sum(len(v) for v in entity_vendor_rows.values())
    print(f"Generated {total_vendors} legacy vendor rows across {len(ENTITIES)} entities")
    print(f"Generated {total_invoices} legacy invoice rows")
    print(f"Generated {total_bank} legacy bank transaction rows")
    print(f"Files written to {LEGACY_DIR}")


if __name__ == "__main__":
    main()
