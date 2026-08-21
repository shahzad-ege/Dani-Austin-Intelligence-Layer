-- ============================================================
-- Migration 004: Social analytics — partial-day fix + demographics
-- ============================================================

-- ITEM 1: partial-day capture fix.
--
-- The connector requests period=day metrics and receives the day-so-far at
-- whatever hour it runs. Proven from real data: Aug 18's Instagram metrics
-- came in at a uniform 34-40% of Aug 17's across six independent metrics
-- (reach, views, total_interactions, likes, comments, accounts_engaged) --
-- a proportional drop that consistent is the signature of an incomplete
-- day, not a real performance collapse.
--
-- Recording WHEN a row was captured makes partial days identifiable rather
-- than silently mixed in with complete ones. Chosen over simply moving the
-- sync time, which still breaks whenever a run is late, retried, or
-- manually triggered.
alter table social_metrics add column if not exists captured_at timestamptz not null default now();

-- The safe default for ANY day-over-day or trend analysis.
create or replace view social_metrics_complete_days as
select
  sm.id,
  sm.account_id,
  sm.metric,
  sm.period_date,
  sm.value,
  sm.source,
  sm.captured_at
from social_metrics sm
where sm.period_date < current_date;

alter view social_metrics_complete_days set (security_invoker = true);

-- Makes the partial-day problem visible rather than requiring prior
-- knowledge of it.
create or replace view social_metrics_freshness as
select
  sa.platform,
  sm.metric,
  sm.period_date,
  sm.value,
  sm.captured_at,
  (sm.period_date >= current_date) as is_partial_day,
  case
    when sm.period_date >= current_date
      then 'PARTIAL - captured mid-day, do not use for trend comparison'
    else 'complete'
  end as completeness
from social_metrics sm
join social_accounts sa on sa.account_id = sm.account_id;

alter view social_metrics_freshness set (security_invoker = true);

-- ITEM 3: Instagram audience demographics.
--
-- Dimensional data (age brackets, gender, cities, countries) doesn't fit
-- social_metrics' account/metric/date/value shape -- forcing it in would
-- mean encoding the dimension into the metric name, which makes querying
-- awkward and breaks the existing "one row per account x metric x date"
-- contract. Own table instead.
create table if not exists social_audience_demographics (
  id bigint generated always as identity primary key,
  account_id text not null references social_accounts(account_id),
  dimension text not null,        -- 'age' | 'gender' | 'city' | 'country'
  dimension_value text not null,  -- '25-34' | 'F' | 'Dallas, Texas' | 'US'
  value numeric(18,4) not null,
  period_date date not null,
  captured_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (account_id, dimension, dimension_value, period_date)
);

create index if not exists idx_social_demographics_lookup
  on social_audience_demographics (account_id, dimension, period_date);

alter table social_audience_demographics enable row level security;
