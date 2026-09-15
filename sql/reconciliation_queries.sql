-- reconciliation_queries.sql
-- Exception-based reconciliation queries: unmatched invoices, unmatched
-- bank transactions, amount variances, and backlog by month. Everything
-- that matches cleanly just closes itself; these are the leftovers.
--
-- Go-live is 2025-07-01, used below to split before/after.
-- Each query is delimited by "-- QUERY: <name>" so
-- etl/invoice_integration_simulation.py can load and run them individually.

-- QUERY: unmatched_invoices
-- Paid invoices with no corresponding bank transaction at all -- these are
-- the reconciliation backlog: payment was recorded, but never confirmed
-- against the bank feed.
SELECT
    i.invoice_id,
    e.entity_name,
    v.vendor_name,
    i.invoice_date,
    i.paid_date,
    i.amount,
    CASE WHEN i.invoice_date < '2025-07-01' THEN 'before' ELSE 'after' END AS period
FROM invoices i
JOIN entities e ON e.entity_id = i.entity_id
JOIN vendors v ON v.vendor_id = i.vendor_id
LEFT JOIN bank_transactions bt ON bt.matched_invoice_id = i.invoice_id
WHERE i.status = 'Paid' AND bt.transaction_id IS NULL;

-- QUERY: unmatched_bank_transactions
-- Bank activity with no invoice reference at all, or referencing an
-- invoice_id that doesn't exist in this entity's invoice table -- stray or
-- misposted items that need investigation before they can be closed.
SELECT
    bt.transaction_id,
    e.entity_name,
    bt.transaction_date,
    bt.amount,
    bt.matched_invoice_id
FROM bank_transactions bt
JOIN entities e ON e.entity_id = bt.entity_id
LEFT JOIN invoices i ON i.invoice_id = bt.matched_invoice_id
WHERE bt.matched_invoice_id IS NULL OR i.invoice_id IS NULL;

-- QUERY: amount_variances
-- Matched pairs where the bank amount doesn't equal the invoice amount --
-- short pays, over-payments, or data-entry typos worth a variance review.
SELECT
    i.invoice_id,
    e.entity_name,
    v.vendor_name,
    i.amount AS invoice_amount,
    bt.amount AS bank_amount,
    ROUND(bt.amount - i.amount, 2) AS variance,
    CASE WHEN i.invoice_date < '2025-07-01' THEN 'before' ELSE 'after' END AS period
FROM invoices i
JOIN bank_transactions bt ON bt.matched_invoice_id = i.invoice_id
JOIN entities e ON e.entity_id = i.entity_id
JOIN vendors v ON v.vendor_id = i.vendor_id
WHERE ABS(bt.amount - i.amount) > 0.01;

-- QUERY: reconciliation_backlog_by_month
-- Count of open exceptions (unmatched paid invoices) by the month the
-- invoice was raised -- this is the "backlog aging" view for the dashboard.
SELECT
    strftime('%Y-%m', i.invoice_date) AS month,
    COUNT(*) AS backlog_count
FROM invoices i
LEFT JOIN bank_transactions bt ON bt.matched_invoice_id = i.invoice_id
WHERE i.status = 'Paid' AND bt.transaction_id IS NULL
GROUP BY month
ORDER BY month;
