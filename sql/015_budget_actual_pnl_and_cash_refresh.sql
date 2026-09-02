-- ============================================================
-- Migration 015: Real Budget/Actual P&L + Cash Flow Forecast Refresh
-- ============================================================
--
-- Source: "2026 DA Brand Forecasted P&L" Google Sheet (12 tabs total).
-- Investigated every tab before importing anything:
--   - "2026 Budget to Actual" + "INPUT" -- REAL, imported (INPUT verified
--     to be the granular source feeding the summary sheet -- cross-checked
--     to the cent before trusting either).
--   - "Cash Projection" -- REAL, verified: Brex balance matched Supabase's
--     own tracked figure to the exact cent, PayPal within $30 (timing).
--     Expense category names matched the EGE-pulled forecast exactly,
--     confirming this is the SAME underlying live model, just more
--     current. Used to REFRESH da_cash_flow_forecast (Sep 2026 - May
--     2027), not create a parallel table. Real differences found vs. the
--     older EGE snapshot (Sep Contracts & Commissions: $484,500 ->
--     $510,000; Relocation: -$400,000 -> -$200,000) -- confirms the live
--     model has moved on since the EGE-side copy was pulled.
--     August 2026 deliberately NOT overwritten -- the new sheet's Aug
--     value is a partial mid-month snapshot (as of 8/28), not comparable
--     to the existing full-month forecast already there.
--   - "SCENARIO 1/2/3" + their CASH variants (6 tabs) -- CONFIRMED STALE,
--     NOT imported. All three are identical copies of each other, dated
--     2024 (not 2026), showing a $2.39M PayPal balance that's never been
--     real in this project. Dead template tabs, never differentiated or
--     updated.
--   - "Revenue Manager", "Jenni", "JD Rogers" -- confirmed genuinely
--     empty, not imported.

create table if not exists da_budget_actual_pnl (
  id bigint generated always as identity primary key,
  month date not null,
  line_item text not null,
  is_subtotal boolean not null default false,
  budget numeric(14,2),
  actual numeric(14,2),
  variance numeric(14,2),
  created_at timestamptz not null default now(),
  unique (month, line_item)
);
alter table da_budget_actual_pnl enable row level security;

-- Real finding from the imported data: 2026 revenue is running at ~46% of
-- budget across every income line (not just one weak category), while
-- operating expenses are running ABOVE budget, driven almost entirely by
-- one unbudgeted line: "Related Business Expenses" ($0 budgeted, $737,635
-- actual for the year). Net Income actual ($710,442) vs. budget
-- ($3,503,538) -- a $2.79M shortfall for the year.
