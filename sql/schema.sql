-- schema.sql
-- Target (post-migration) relational schema for the Meridian Group data
-- platform. Portable ANSI-ish SQL, built and tested against SQLite;
-- notes below flag the handful of lines that would differ on Postgres.

DROP TABLE IF EXISTS bank_transactions;
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS vendor_entity_ids;
DROP TABLE IF EXISTS vendors;
DROP TABLE IF EXISTS entities;

CREATE TABLE entities (
    entity_id     INTEGER PRIMARY KEY,          -- Postgres: SERIAL PRIMARY KEY
    entity_name   TEXT NOT NULL UNIQUE,
    entity_code   TEXT NOT NULL UNIQUE
);

-- One row per real-world vendor, deduplicated across the three legacy
-- spreadsheets. This is the core output of the migration: before this
-- table existed, the same vendor could appear under a different local ID
-- (and slightly different name formatting) in each entity's own sheet.
CREATE TABLE vendors (
    vendor_id           INTEGER PRIMARY KEY,    -- Postgres: SERIAL PRIMARY KEY
    vendor_name         TEXT NOT NULL,
    category            TEXT,
    standard_terms_days INTEGER NOT NULL,
    tax_id              TEXT
);

-- Crosswalk preserving each entity's original legacy vendor ID, so the
-- migration is auditable: any row can be traced back to its source system.
CREATE TABLE vendor_entity_ids (
    vendor_id         INTEGER NOT NULL REFERENCES vendors(vendor_id),
    entity_id         INTEGER NOT NULL REFERENCES entities(entity_id),
    legacy_vendor_id  TEXT NOT NULL,
    legacy_active_flag TEXT,
    PRIMARY KEY (entity_id, legacy_vendor_id)
);

CREATE TABLE invoices (
    invoice_id     TEXT PRIMARY KEY,
    entity_id      INTEGER NOT NULL REFERENCES entities(entity_id),
    vendor_id      INTEGER NOT NULL REFERENCES vendors(vendor_id),
    invoice_date   DATE NOT NULL,
    due_date       DATE NOT NULL,
    paid_date      DATE,
    amount         REAL NOT NULL,
    status         TEXT NOT NULL,
    po_reference   TEXT,
    is_duplicate   INTEGER NOT NULL DEFAULT 0   -- flagged by migrate_and_cleanse.py
);

CREATE TABLE bank_transactions (
    transaction_id      TEXT PRIMARY KEY,
    entity_id           INTEGER NOT NULL REFERENCES entities(entity_id),
    matched_invoice_id  TEXT REFERENCES invoices(invoice_id),
    transaction_date    DATE NOT NULL,
    amount              REAL NOT NULL
);

CREATE INDEX idx_invoices_vendor ON invoices(vendor_id);
CREATE INDEX idx_invoices_entity_date ON invoices(entity_id, invoice_date);
CREATE INDEX idx_bank_matched_invoice ON bank_transactions(matched_invoice_id);
