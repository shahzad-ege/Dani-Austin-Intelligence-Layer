-- ============================================================
-- Dani Austin Supabase — Initial Schema
-- Mirrors what's live in the "Dani Austin" Supabase project.
-- Run via `supabase db push` or psql against a fresh project.
-- ============================================================

-- 1. QuickBooks — booked truth
create table if not exists qb_da_transaction_lines (
  id bigint generated always as identity primary key,
  qb_txn_id text not null,  -- QuickBooks' real internal Id, always present
  qb_line_id text,          -- line-item ID within the transaction (multi-line support)
  qb_txn_type text,         -- Purchase | Bill | Invoice | SalesReceipt | Deposit
  txn_date date not null,
  category text not null check (category in ('income', 'expense')),
  account text not null,
  source text,
  amount numeric(14,2) not null,
  memo text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (qb_txn_id, qb_line_id)
);

create index if not exists idx_qb_txn_date on qb_da_transaction_lines (txn_date);
create index if not exists idx_qb_source on qb_da_transaction_lines (source);

-- Stores the current (rotated) QuickBooks refresh token. QuickBooks
-- rotates this token on every use -- without persisting it here, the
-- .env value goes stale after the first successful run and every
-- scheduled run after that fails silently.
create table if not exists qb_oauth_credentials (
  id bigint generated always as identity primary key,
  realm_id text not null unique,
  refresh_token text not null,
  updated_at timestamptz not null default now()
);

alter table qb_oauth_credentials enable row level security;

create or replace view da_pnl as
select
  date_trunc('month', txn_date)::date as month,
  account,
  category,
  sum(amount) as amount
from qb_da_transaction_lines
group by 1, 2, 3;

alter view da_pnl set (security_invoker = true);

create or replace view da_revenue_actuals as
select
  date_trunc('month', txn_date)::date as month,
  source as business_unit,
  sum(amount) as amount
from qb_da_transaction_lines
where category = 'income'
group by 1, 2;

alter view da_revenue_actuals set (security_invoker = true);

-- 2. Cash (Plaid / Chase, Brex, PayPal — all feed this same table) — reused
create table if not exists da_cash_current_balance (
  id bigint generated always as identity primary key,
  account_name text not null,
  current_balance numeric(14,2) not null,
  as_of timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_cash_as_of on da_cash_current_balance (as_of desc);

-- da_cash_current_balance is append-only (a running daily log per account),
-- not a single current-state table -- these two views derive "latest
-- balance per account" and "total across all accounts" on demand, rather
-- than storing a pre-computed combined figure that could drift out of sync.
create or replace view da_cash_balance_latest as
select distinct on (account_name)
  account_name,
  current_balance,
  as_of
from da_cash_current_balance
order by account_name, as_of desc;

alter view da_cash_balance_latest set (security_invoker = true);

create or replace view da_total_cash_balance as
select
  sum(current_balance) as total_cash,
  max(as_of) as as_of_latest,
  count(*) as accounts_included
from da_cash_balance_latest;

alter view da_total_cash_balance set (security_invoker = true);

-- PayPal-only total (Dani Austin + Katelyn's accounts combined) -- narrower
-- than da_total_cash_balance above, which covers every cash source.
create or replace view da_paypal_balance_total as
select
  sum(current_balance) as total_paypal_cash,
  max(as_of) as as_of_latest,
  count(*) as accounts_included
from da_cash_balance_latest
where account_name like 'PayPal%';

alter view da_paypal_balance_total set (security_invoker = true);

-- 3. Cash flow forecast — migrated from EGE
create table if not exists da_cash_flow_forecast (
  id bigint generated always as identity primary key,
  month date not null,
  line_item text not null,
  value numeric(14,2) not null,
  created_at timestamptz not null default now(),
  unique (month, line_item)
);

create table if not exists da_cash_flow_recurring_assumptions (
  id bigint generated always as identity primary key,
  line_item text not null,
  monthly_amount numeric(14,2) not null,
  starts_month date,
  ends_month date,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists da_cash_flow_monthly_actuals (
  id bigint generated always as identity primary key,
  month date not null,
  line_item text not null,
  amount numeric(14,2) not null,
  created_at timestamptz not null default now(),
  unique (month, line_item)
);

-- 4. Airtable — pipeline (Brand Partnerships)
create table if not exists airtable_partnerships (
  id bigint generated always as identity primary key,
  deal_id text not null,
  invoice_no text,
  status text not null,
  deliverable_platform text,
  client text,
  is_repeat boolean,
  gross_amt numeric(14,2),
  net_amt numeric(14,2),
  month_committed date,
  month_completed date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (deal_id)
);

create index if not exists idx_airtable_invoice on airtable_partnerships (invoice_no);
create index if not exists idx_airtable_month_completed on airtable_partnerships (month_completed);
create index if not exists idx_airtable_platform on airtable_partnerships (deliverable_platform);

-- 5. Revenue Projections (forecast) — Katelyn Excel
create table if not exists da_revenue_forecast (
  id bigint generated always as identity primary key,
  month date not null,
  business_unit text not null,
  estimate numeric(14,2),
  goal numeric(14,2),
  created_at timestamptz not null default now(),
  unique (month, business_unit)
);

-- 6. Affiliate — manual export (Amazon + LTK)
create table if not exists affiliate_revenue (
  id bigint generated always as identity primary key,
  month date not null,
  platform text not null,
  gross_commission numeric(14,2),
  clicks bigint,
  created_at timestamptz not null default now(),
  unique (month, platform)
);

-- 6b. Direct-brand affiliate/commission deals (e.g. Stanley) — distinct from
-- platform-marketplace affiliate revenue above. Discovered via Katelyn's
-- revenue projections sheet; has no equivalent in the original scoping docs.
create table if not exists affiliate_commission_deals (
  id bigint generated always as identity primary key,
  brand text not null,
  month date not null,
  estimated numeric(14,2),
  actual numeric(14,2),
  created_at timestamptz not null default now(),
  unique (brand, month)
);

-- 7. Social — foundation/attention layer
create table if not exists social_accounts (
  id bigint generated always as identity primary key,
  platform text not null,
  handle text not null,
  account_id text not null,
  is_core boolean not null default true,
  created_at timestamptz not null default now(),
  unique (account_id)
);

create table if not exists social_metrics (
  id bigint generated always as identity primary key,
  account_id text not null references social_accounts(account_id),
  metric text not null,
  period_date date not null,
  value numeric(18,4) not null,
  source text not null default 'api',
  created_at timestamptz not null default now(),
  unique (account_id, metric, period_date, source)
);

create index if not exists idx_social_metrics_lookup on social_metrics (metric, period_date);

-- Engagement rate, DERIVED not stored -- consistent with this project's rule
-- that computed/combined figures are always views over atomic rows, never
-- stored values that can go stale.
-- Formula: total_interactions / followers * 100 (standard definition).
-- Requires the Meta connector's `total_interactions` metric, which is
-- Instagram-only (Facebook has no equivalent that the live API accepts).
create or replace view da_social_engagement_rate as
select
  sa.platform,
  sa.handle,
  sm_int.period_date,
  sm_int.value as total_interactions,
  sm_fol.value as followers,
  round((sm_int.value / nullif(sm_fol.value, 0)) * 100, 4) as engagement_rate_pct
from social_metrics sm_int
join social_metrics sm_fol
  on sm_fol.account_id = sm_int.account_id
 and sm_fol.period_date = sm_int.period_date
 and sm_fol.metric = 'followers'
join social_accounts sa on sa.account_id = sm_int.account_id
where sm_int.metric = 'total_interactions';

alter view da_social_engagement_rate set (security_invoker = true);

-- 8. Podcast audience (Podstock) — pending access
create table if not exists podcast_metrics (
  id bigint generated always as identity primary key,
  show_id text not null,
  platform text not null,
  metric text not null,
  period_date date not null,
  value numeric(18,4) not null,
  created_at timestamptz not null default now(),
  unique (show_id, platform, metric, period_date)
);

-- 9. Rollup — syncs to EGE hub
create table if not exists da_entity_summary (
  id bigint generated always as identity primary key,
  month date not null,
  metric text not null,
  value numeric(18,4) not null,
  synced_at timestamptz,
  created_at timestamptz not null default now(),
  unique (month, metric)
);

-- ============================================================
-- Row Level Security — secret-key only, no public/anon reads.
-- No policies are created intentionally: the service-role key
-- bypasses RLS by design, which is the intended access path for
-- run_all.py and the DA Claude project's MCP connector.
-- ============================================================

alter table qb_da_transaction_lines enable row level security;
alter table da_cash_current_balance enable row level security;
alter table da_cash_flow_forecast enable row level security;
alter table da_cash_flow_recurring_assumptions enable row level security;
alter table da_cash_flow_monthly_actuals enable row level security;
alter table airtable_partnerships enable row level security;
alter table da_revenue_forecast enable row level security;
alter table affiliate_revenue enable row level security;
alter table affiliate_commission_deals enable row level security;
alter table social_accounts enable row level security;
alter table social_metrics enable row level security;
alter table podcast_metrics enable row level security;
alter table da_entity_summary enable row level security;
