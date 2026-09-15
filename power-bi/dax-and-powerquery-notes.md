# Power BI Notes — Power Query (M) and DAX

The dashboard in `/dashboard` is plain HTML/JS so anyone with the repo link can open it without a Power BI license. In an actual enterprise deployment this reporting layer would sit in Power BI, connected straight to the SQL data platform — this file is that version: the Power Query and DAX that would produce the same KPIs against the same schema.

## Power Query (M) — loading and shaping

```m
let
    Source = Sql.Database("localhost", "erp_case_study"),
    Invoices = Source{[Schema="dbo",Item="invoices"]}[Data],
    BankTx = Source{[Schema="dbo",Item="bank_transactions"]}[Data],
    Vendors = Source{[Schema="dbo",Item="vendors"]}[Data],

    // Join invoices to their matched bank transaction (left outer —
    // unmatched invoices are exactly the reconciliation backlog)
    JoinedRecon = Table.NestedJoin(
        Invoices, {"invoice_id"},
        BankTx, {"matched_invoice_id"},
        "BankMatch", JoinKind.LeftOuter
    ),
    ExpandedRecon = Table.ExpandTableColumn(
        JoinedRecon, "BankMatch",
        {"transaction_date", "amount"}, {"bank_transaction_date", "bank_amount"}
    ),

    // Period flag mirrors the CASE WHEN in kpi_queries.sql
    WithPeriod = Table.AddColumn(
        ExpandedRecon, "period",
        each if [invoice_date] < #date(2025, 7, 1) then "before" else "after"
    ),

    WithCycleTime = Table.AddColumn(
        WithPeriod, "cycle_time_days",
        each if [bank_transaction_date] <> null
             then Duration.Days([bank_transaction_date] - [invoice_date])
             else null
    )
in
    WithCycleTime
```

## DAX measures

```dax
Avg Cycle Time (Days) =
AVERAGE ( 'FactReconciliation'[cycle_time_days] )

Avg Cycle Time — Before Go-Live =
CALCULATE ( [Avg Cycle Time (Days)], 'FactReconciliation'[period] = "before" )

Avg Cycle Time — After Go-Live =
CALCULATE ( [Avg Cycle Time (Days)], 'FactReconciliation'[period] = "after" )

Cycle Time % Improvement =
DIVIDE (
    [Avg Cycle Time — Before Go-Live] - [Avg Cycle Time — After Go-Live],
    [Avg Cycle Time — Before Go-Live]
)

Invoice Error Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( 'FactInvoices' ), 'FactInvoices'[is_duplicate] = TRUE || ISBLANK ( 'FactInvoices'[po_reference] ) ),
    COUNTROWS ( 'FactInvoices' )
)

Open Backlog Items =
CALCULATE (
    COUNTROWS ( 'FactInvoices' ),
    'FactInvoices'[status] = "Paid",
    ISBLANK ( 'FactInvoices'[bank_transaction_date] )
)

Backlog Trend (by Invoice Month) =
CALCULATE (
    [Open Backlog Items],
    ALLEXCEPT ( 'FactInvoices', 'FactInvoices'[invoice_month] )
)
```

## Suggested visuals

- KPI cards: `Avg Cycle Time — After Go-Live` with `Cycle Time % Improvement` as the card's comparison value
- Line chart: `Backlog Trend (by Invoice Month)`, with a reference line at the go-live date
- Table: `Invoice Error Rate` sliced by entity, to catch a regression at a single entity before it shows up group-wide
