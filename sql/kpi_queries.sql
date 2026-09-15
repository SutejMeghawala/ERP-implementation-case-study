-- kpi_queries.sql
-- Before/after and monthly-trend KPI queries. GO_LIVE_DATE = 2025-07-01.
-- Each query is delimited by a "-- QUERY: <name>" marker so
-- etl/invoice_integration_simulation.py can load and run them individually.

-- QUERY: reconciliation_cycle_time_before_after
-- Average days between invoice date and the bank transaction that closes
-- it, for matched paid invoices -- the direct measure of "how long does
-- reconciliation take."
SELECT
    CASE WHEN i.invoice_date < '2025-07-01' THEN 'before' ELSE 'after' END AS period,
    ROUND(AVG(julianday(bt.transaction_date) - julianday(i.invoice_date)), 1) AS avg_cycle_time_days,
    COUNT(*) AS matched_invoice_count
FROM invoices i
JOIN bank_transactions bt ON bt.matched_invoice_id = i.invoice_id
GROUP BY period;

-- QUERY: vendor_payment_turnaround_before_after
-- Average days between invoice date and paid date, across all paid
-- invoices -- how long it actually takes to get a vendor paid.
SELECT
    CASE WHEN invoice_date < '2025-07-01' THEN 'before' ELSE 'after' END AS period,
    ROUND(AVG(julianday(paid_date) - julianday(invoice_date)), 1) AS avg_turnaround_days,
    COUNT(*) AS paid_invoice_count
FROM invoices
WHERE status = 'Paid'
GROUP BY period;

-- QUERY: invoice_error_rate_before_after
-- Share of invoices that are either a flagged duplicate entry or missing
-- their PO reference -- the data-quality defects a standardized intake
-- process is meant to catch.
SELECT
    CASE WHEN invoice_date < '2025-07-01' THEN 'before' ELSE 'after' END AS period,
    ROUND(100.0 * SUM(CASE WHEN is_duplicate = 1 OR po_reference IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS error_rate_pct,
    COUNT(*) AS total_invoices
FROM invoices
GROUP BY period;

-- QUERY: monthly_kpi_trend
-- Month-by-month view combining turnaround and error rate, for the
-- dashboard's trend line.
SELECT
    strftime('%Y-%m', invoice_date) AS month,
    ROUND(AVG(CASE WHEN status = 'Paid' THEN julianday(paid_date) - julianday(invoice_date) END), 1) AS avg_turnaround_days,
    ROUND(100.0 * SUM(CASE WHEN is_duplicate = 1 OR po_reference IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS error_rate_pct,
    COUNT(*) AS invoice_count
FROM invoices
GROUP BY month
ORDER BY month;
