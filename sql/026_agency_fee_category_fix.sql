-- ============================================================
-- Migration 026: Agency Fee category fix (Sep 2026)
-- ============================================================
-- Found via reconciliation against a real QuickBooks P&L export
-- (Jan-Sep 2026) and Katelyn's confirmed figures. Two accounts were
-- already correctly routed to their business unit (Partnerships,
-- Podcast) in an earlier fix, but the category field itself was never
-- corrected -- both are genuine expense accounts still tagged
-- category='income' due to the entity-type-based hardcoding bug.
--
-- Real, confirmed impact: this was inflating Partnerships 2026 YTD
-- income by exactly $69,333.32 -- after the fix, our Partnerships
-- total ($1,474,316.66) matches the real QuickBooks P&L exactly.
update qb_da_transaction_lines set category = 'expense'
where account = 'Agency Fee' and category = 'income';
-- Full history: 91 rows, $498,701.01

update qb_da_transaction_lines set category = 'expense'
where account = 'Podcast Agency Fee' and category = 'income';
-- Full history: 299 rows, $267,428.38 (this account had many more
-- individual transaction rows than the standalone Agency Fee account)

-- Regression guard, matching the established Non-Operating trigger
-- pattern -- re-verified adversarially afterward: a deliberate attempt
-- to revert one row to category='income' was correctly blocked.
create or replace function enforce_agency_fee_category()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.account in ('Agency Fee', 'Podcast Agency Fee') then
    new.category := 'expense';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_enforce_agency_fee_category on qb_da_transaction_lines;
create trigger trg_enforce_agency_fee_category
before insert or update on qb_da_transaction_lines
for each row execute function enforce_agency_fee_category();

-- ============================================================
-- STILL OPEN, NOT YET FIXED -- needs further investigation
-- ============================================================
-- 1. Platform Affiliate - LTK: zero transactions synced for all of
--    2026, despite the account being correctly classified and the
--    real QuickBooks P&L showing $123,193.38 in genuine 2026 LTK
--    revenue. Account has 367 real historical rows ($3.87M all-time)
--    but none in 2026 -- a real sync gap, not a classification bug.
--
-- 2. Amazon Platform Affiliate Revenue: short by exactly $1,500/month
--    for Jan-Jun 2026 (6 months x $1,500 = $9,000 total gap), but
--    July 2026 matches the real P&L exactly. Consistent, clean
--    pattern -- worth investigating what specific $1,500 monthly item
--    stopped being missed starting in July.

-- ============================================================
-- Cash forecast v2 (Sep 2026) -- Katelyn's request: use real
-- AR/invoicing to predict cash flow, with real expense modeling.
-- ============================================================
--
-- MAJOR FINDING, more significant than the category bugs above:
-- Salaries & Wages ($360,464.13 for the year -- the single largest
-- expense line in the entire real P&L) does not exist ANYWHERE in
-- qb_da_transaction_lines, in any category. Root cause confirmed by
-- reading the connector directly: ENTITY_CONFIG only queries Purchase,
-- Bill, Invoice, SalesReceipt, Deposit -- it has never queried
-- JournalEntry. Payroll processors (Gusto, ADP, etc.) almost
-- universally post payroll runs as journal entries, not bills. This
-- is a genuine architectural gap, not a data-quality bug -- adding
-- JournalEntry support is real, separate engineering work (journal
-- entries have debit/credit line structure, different from
-- Purchase/Bill's simple expense-line shape, and would need a live
-- diagnostic to confirm the real API response shape before building).
--
-- Given this gap, da_cash_forecast_v2 deliberately uses REAL, confirmed
-- monthly figures from the actual QB P&L PDF for payroll (not our own
-- incomplete sync data), combined with our own (unaffected) AR
-- collection data for the inflow side.
create view da_cash_forecast_v2
with (security_invoker = true)
as
with real_inputs as (
  select
    (select total_cash from da_total_cash_balance) as current_cash,
    (select expected_next_30_days from da_ar_expected_collections) as ar_next_30,
    (select expected_next_60_days - expected_next_30_days from da_ar_expected_collections) as ar_days_31_60,
    (select expected_next_90_days - expected_next_60_days from da_ar_expected_collections) as ar_days_61_90
)
select
  current_cash, ar_next_30, ar_days_31_60, ar_days_61_90,
  59200.00 as payroll_monthly_estimate,
  0.00 as relocation_monthly_estimate,
  70000.00 as core_opex_monthly_estimate,
  'IRREGULAR -- quarterly estimated payments, ranges $0-$75,000/month historically. Not modeled as a smooth monthly average.' as income_tax_note
from real_inputs;
