-- ============================================================
-- Migration 011: Accounts Receivable aging
-- ============================================================
--
-- Built in response to a direct request: current AR position, plus
-- revenue expected to be collected in 30/60/90 days. This needed NEW data
-- capture -- the existing qb_da_transaction_lines only holds line-item
-- amounts, never invoice-level Balance (remaining unpaid amount) or
-- DueDate, which are properties of the invoice header, not its lines.
--
-- qb_da_invoices is intentionally NOT filtered by the 90-day rolling
-- window the regular transaction sync uses -- AR aging cares about which
-- invoices are STILL OPEN today regardless of age. A 2-year-old unpaid
-- invoice is exactly as relevant to a current AR position as one from
-- last week. Synced via `python qb_connector.py --ar-aging`, a separate
-- mode from the regular sync.

create table if not exists qb_da_invoices (
  id bigint generated always as identity primary key,
  qb_invoice_id text not null unique,
  customer_name text,
  txn_date date,
  due_date date,
  total_amount numeric(14,2),
  balance numeric(14,2),  -- remaining UNPAID amount; 0 = fully paid
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_qb_invoices_balance on qb_da_invoices (balance) where balance > 0;
create index if not exists idx_qb_invoices_due_date on qb_da_invoices (due_date);

alter table qb_da_invoices enable row level security;

-- Current total AR position.
create or replace view da_ar_current_position as
select
  count(*) as open_invoice_count,
  sum(balance) as total_outstanding,
  sum(balance) filter (where due_date < current_date) as total_overdue,
  min(due_date) filter (where due_date < current_date) as oldest_overdue_due_date
from qb_da_invoices
where balance > 0;

alter view da_ar_current_position set (security_invoker = true);

-- Per-invoice detail with discrete aging buckets.
create or replace view da_ar_aging_detail as
select
  qb_invoice_id, customer_name, txn_date, due_date, balance,
  (due_date - current_date) as days_until_due,
  case
    when due_date < current_date then 'overdue'
    when due_date <= current_date + interval '30 days' then 'due_0_30'
    when due_date <= current_date + interval '60 days' then 'due_31_60'
    when due_date <= current_date + interval '90 days' then 'due_61_90'
    else 'due_90_plus'
  end as aging_bucket
from qb_da_invoices
where balance > 0;

alter view da_ar_aging_detail set (security_invoker = true);

-- The direct answer to "revenue expected in 30/60/90 days" -- cumulative
-- sums (everything due within N days), not just the discrete slice, since
-- that's how this question is normally asked.
create or replace view da_ar_expected_collections as
select
  sum(balance) filter (where due_date >= current_date and due_date <= current_date + interval '30 days') as expected_next_30_days,
  sum(balance) filter (where due_date >= current_date and due_date <= current_date + interval '60 days') as expected_next_60_days,
  sum(balance) filter (where due_date >= current_date and due_date <= current_date + interval '90 days') as expected_next_90_days,
  sum(balance) filter (where due_date < current_date) as already_overdue,
  sum(balance) as total_outstanding
from qb_da_invoices
where balance > 0;

alter view da_ar_expected_collections set (security_invoker = true);

-- Follow-up: daily automation + settlement tracking.
-- qb_da_invoices alone can't answer "was this settled, and when" -- it's
-- upsert-only, so a paid invoice's prior open balance is simply overwritten
-- and lost. qb_da_invoices_daily_snapshot solves this the same way
-- da_cash_current_balance already does for cash: an append-only log, one
-- row per invoice per day, so history is preserved even as current state
-- changes. sync_ar_aging() now writes to both tables on every run, and is
-- wired into run_all.py's daily automated sync (as "quickbooks_ar_aging"),
-- same isolation-per-connector pattern as everything else in that file.

create table if not exists qb_da_invoices_daily_snapshot (
  id bigint generated always as identity primary key,
  qb_invoice_id text not null,
  customer_name text,
  due_date date,
  balance numeric(14,2) not null,
  snapshot_date date not null default current_date,
  created_at timestamptz not null default now(),
  unique (qb_invoice_id, snapshot_date)
);

create index if not exists idx_ar_snapshot_invoice on qb_da_invoices_daily_snapshot (qb_invoice_id, snapshot_date);

alter table qb_da_invoices_daily_snapshot enable row level security;

-- Settlement detection: an invoice whose most recent snapshot shows
-- balance=0 (paid), but an earlier snapshot shows balance>0 (was open).
-- Only shows real results once 2+ days of snapshot history exist --
-- correctly empty on day 1, not an error.
create or replace view da_ar_recently_settled as
with latest as (
  select distinct on (qb_invoice_id) qb_invoice_id, customer_name, balance as current_balance, snapshot_date as latest_snapshot
  from qb_da_invoices_daily_snapshot
  order by qb_invoice_id, snapshot_date desc
),
first_seen_open as (
  select qb_invoice_id, min(snapshot_date) as first_open_date, max(balance) as max_balance_seen
  from qb_da_invoices_daily_snapshot
  where balance > 0
  group by qb_invoice_id
)
select
  l.qb_invoice_id, l.customer_name, f.max_balance_seen as amount_settled,
  f.first_open_date as first_seen_open, l.latest_snapshot as settled_by
from latest l
join first_seen_open f on f.qb_invoice_id = l.qb_invoice_id
where l.current_balance = 0
order by l.latest_snapshot desc;

alter view da_ar_recently_settled set (security_invoker = true);
