-- ============================================================
-- Migration 031: Sep 23 2026 full-project audit -- DB fixes (all applied live)
-- ============================================================

-- 1. updated_at never changed on UPDATE for 5 tables (default now() only fires
--    on INSERT, no trigger). Made freshness unmeasurable -- e.g. Airtable looked
--    17 days stale while actually syncing daily. Shared trigger added.
create or replace function set_updated_at()
returns trigger language plpgsql security invoker set search_path = ''
as $$ begin new.updated_at := now(); return new; end; $$;
do $$
declare t text;
begin
  foreach t in array array['airtable_partnerships','qb_da_invoices','qb_da_transaction_lines','qb_oauth_credentials','social_posts'] loop
    execute format('drop trigger if exists trg_set_updated_at on public.%I', t);
    execute format('create trigger trg_set_updated_at before update on public.%I for each row execute function set_updated_at()', t);
  end loop;
end $$;

-- 2. ROOT CAUSE of the 189-row needs_review regression: the older trigger
--    (enforce_non_operating_category) only fires when source is ALREADY
--    'Non-Operating', but 9 Non-Operating accounts were never added to
--    qb_account_business_unit_map -- earlier fixes used one-time UPDATEs, which
--    every full sync silently undid. Added them (plus Bad Debt Expense and
--    Pension Plan Expense -> Overhead) to the map, the real source of truth.
--    "Home Development - Nashville" deliberately left unmapped pending Katelyn.
insert into qb_account_business_unit_map (account_name, business_unit, notes)
select v.a, v.b, v.n from (values
  ('Payroll Liability','Non-Operating','Sep 23 2026 audit'),
  ('Pension Plan Payable','Non-Operating','Sep 23 2026 audit'),
  ('Business Checking 8207','Non-Operating','Sep 23 2026 audit'),
  ('Brex - Cash Account','Non-Operating','Sep 23 2026 audit'),
  ('SACA Brex Account','Non-Operating','Sep 23 2026 audit'),
  ('Reconciliation Discrepancies','Non-Operating','Sep 23 2026 audit'),
  ('Purchase Accrual','Non-Operating','Sep 23 2026 audit'),
  ('CLOSED CC 4454 (deleted)','Non-Operating','Sep 23 2026 audit'),
  ('Prepaid Contract Revenue','Non-Operating','Sep 23 2026 audit'),
  ('Other General & Administrative Expenses:Bad Debt Expense','Overhead','Sep 23 2026 audit; NOT Katelyn-confirmed'),
  ('Payroll:Pension Plan Expense','Overhead','Sep 23 2026 audit; NOT Katelyn-confirmed')
) v(a,b,n)
where not exists (select 1 from qb_account_business_unit_map m where m.account_name = v.a);

-- 3. No index on account, despite nearly every financial query filtering by it.
create index if not exists idx_qb_account_txn_date on qb_da_transaction_lines (account, txn_date);

-- NOT CHANGED, recommended: the upsert conflict key (qb_txn_id, qb_line_id)
-- omits qb_txn_type. QB Ids appear to share one sequence across entity types
-- in this company (0 cross-type Id collisions found today), so no data loss
-- exists -- but adding qb_txn_type to the key would remove the dependency on
-- that assumption. Needs a coordinated writer.py + constraint change.
