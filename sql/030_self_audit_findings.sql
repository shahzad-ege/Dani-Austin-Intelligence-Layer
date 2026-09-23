-- ============================================================
-- Migration 030: Self-audit findings and Non-Operating trigger (Sep 2026)
-- ============================================================
-- Performed a systematic audit for gaps beyond the three already
-- found (payroll, LTK, CreditMemo). Real findings, in order of
-- materiality:

-- FIXED: Non-Operating classification had NO ongoing enforcement --
-- unlike Agency Fee (which has a trigger), the original Non-Operating
-- fix was a one-time UPDATE on existing rows. Today's full-history
-- backfill picked up 189 new rows across known Non-Operating accounts
-- (Payroll Liability, Pension Plan Payable, Business Checking 8207,
-- Brex accounts, etc.) that landed in needs_review with the wrong
-- category. Fixed the existing rows and added a real trigger
-- (enforce_non_operating_accounts) covering the full known list, so
-- this can't silently regress on any future sync. Adversarially
-- re-tested: a deliberate attempt to revert one row was correctly blocked.
create or replace function enforce_non_operating_accounts()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.account in ('Payroll Liability', 'Pension Plan Payable', 'Business Checking 8207', 'Brex - Cash Account',
                      'SACA Brex Account', 'Reconciliation Discrepancies', 'Purchase Accrual', 'CLOSED CC 4454 (deleted)',
                      'Prepaid Contract Revenue', 'Accounts Receivable (A/R)', 'Brex - Credit Cards',
                      'Federal Income Tax Payable', 'Owner''s Contribution', 'Owner''s Equity', 'Owner''s Distribution',
                      'Opening Balance Equity', 'Prepaid Agency Fee', 'Income Tax') then
    new.category := 'non_operating';
    new.source := 'Non-Operating';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_enforce_non_operating_accounts on qb_da_transaction_lines;
create trigger trg_enforce_non_operating_accounts
before insert or update on qb_da_transaction_lines
for each row execute function enforce_non_operating_accounts();

-- Cleaned up the remaining needs_review backlog from today's backfill:
-- Bad Debt Expense and Pension Plan Expense mapped to Overhead
-- (matching established G&A/Payroll patterns). "Home Development -
-- Nashville" (5 rows, -$60,608.10) deliberately left unclassified --
-- a genuinely new, unusual account name with no clear precedent to
-- match against. Worth asking Katelyn directly rather than guessing.
update qb_da_transaction_lines set source = 'Overhead'
where account in ('Other General & Administrative Expenses:Bad Debt Expense', 'Payroll:Pension Plan Expense')
  and source = 'needs_review';

-- ============================================================
-- NOT FIXED -- flagged for further investigation, real stakes
-- ============================================================
-- 1. Payroll:Payroll Tax Expense has THREE separate real sources:
--    - Deposit (10 rows, $108,388.36, category=income) -- unusual,
--      possibly a real tax refund/credit, possibly a bug
--    - JournalEntry (453 rows, -$180,277.90, expense) -- our correct,
--      recently-built extraction, confirmed working
--    - Purchase (237 rows, -$488,197.88, expense) -- a real, separate,
--      LARGER expense stream that stopped in 2024 while JournalEntry
--      continues to today
--    Real, unresolved question: do Purchase and JournalEntry represent
--    the same real tax liability recorded twice (accrual + payment,
--    both hitting the expense account), or two genuinely different
--    real costs? Cannot be resolved from this data alone -- needs
--    either live QB detail on the Purchase-side transactions or
--    Katelyn's direct knowledge of how payroll tax was recorded before
--    vs after 2024.
--
-- 2. "Expense Reimbursement - Divi" ($193,348.78, category=income,
--    3 rows) -- plausibly correct per Katelyn's own explanation of how
--    reimbursements work (invoiced via the revenue process, netted
--    against the original expense), but large enough to be worth an
--    explicit confirmation rather than assuming.
--
-- 3. "Home Development - Nashville" ($60,608.10, 5 rows) -- genuinely
--    new account name, no established classification precedent.
