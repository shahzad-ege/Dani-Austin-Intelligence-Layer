-- ============================================================
-- Migration 035: fixes for the Oct 21 2026 data-health bug list
-- ============================================================
-- Apply BEFORE pushing the matching connector code (it adds columns and
-- conflict keys the new code writes to). Idempotent: safe to re-run.
--
-- Nothing here deletes real data outright. Rows that are removed
-- (fake TikTok zeros, same-day duplicate post-metric snapshots) are
-- first copied to the `archive` schema, which PostgREST does not expose.
-- ============================================================

begin;

create schema if not exists archive;
revoke all on schema archive from public, anon, authenticated;

-- ------------------------------------------------------------
-- #1 (Critical) Prepaid Expenses counted as a P&L expense
-- #10 'Channel expenses:PayPal expense' unmapped
-- ------------------------------------------------------------
update qb_account_business_unit_map
   set business_unit = 'Non-Operating',
       notes = 'Balance-sheet asset (prepaid, not yet expensed). Reclassified Oct 22 2026 (bug list #1): '
            || 'was counting ~$100.6K of 2026 prepayments as Overhead expense.'
 where account_name = 'Prepaid Expenses';

insert into qb_account_business_unit_map (account_name, business_unit, notes)
values ('Channel expenses:PayPal expense', 'Overhead',
        'Added Oct 22 2026 (bug list #10). Matches the Merchant Fees - PayPal precedent. '
     || 'Not Katelyn-confirmed; she may reclass the single $700 line (Purchase 41967/1).')
on conflict (account_name) do update
  set business_unit = excluded.business_unit, notes = excluded.notes;

-- Root cause of #1 recurring: the Non-Operating guard trigger used a
-- hard-coded account list, so every newly-identified balance-sheet
-- account had to be added in two places and Prepaid Expenses never was.
-- The trigger now reads the mapping table, so a single mapping row is
-- enough and a full re-sync can never undo it.
create or replace function public.enforce_non_operating_accounts()
returns trigger language plpgsql set search_path to '' as $f$
begin
  if exists (select 1 from public.qb_account_business_unit_map m
              where m.account_name = new.account
                and m.business_unit = 'Non-Operating') then
    new.category := 'non_operating';
    new.source   := 'Non-Operating';
  end if;
  return new;
end; $f$;

update qb_da_transaction_lines t
   set source = 'Non-Operating', category = 'non_operating'
  from qb_account_business_unit_map m
 where m.account_name = t.account
   and m.business_unit = 'Non-Operating'
   and (t.source is distinct from 'Non-Operating' or t.category is distinct from 'non_operating');

update qb_da_transaction_lines t
   set source = m.business_unit
  from qb_account_business_unit_map m
 where m.account_name = t.account
   and t.source = 'needs_review'
   and m.business_unit <> 'Non-Operating';

-- ------------------------------------------------------------
-- #3 TikTok API engagement written as 0 for 29 days
-- social_metrics.value is NOT NULL, so the fake zeros are archived and
-- removed rather than nulled. The fixed connector never writes them again.
-- ------------------------------------------------------------
create table if not exists archive.social_metrics_tiktok_fake_zeros_20261022
  (like public.social_metrics);   -- plain LIKE: no identity, so ids copy as-is

insert into archive.social_metrics_tiktok_fake_zeros_20261022
select * from social_metrics
 where account_id = '-000K2C4dnrBsCwG9bthaxx0wNWEOFKEBVbM'
   and source = 'api' and metric in ('views','likes','comments','shares') and value = 0
   and not exists (select 1 from archive.social_metrics_tiktok_fake_zeros_20261022 a where a.id = social_metrics.id);

delete from social_metrics
 where account_id = '-000K2C4dnrBsCwG9bthaxx0wNWEOFKEBVbM'
   and source = 'api' and metric in ('views','likes','comments','shares') and value = 0;

-- ------------------------------------------------------------
-- #4 YouTube: rows mixed three different meanings under one key
--   2026-09-23            -> lifetime totals (backfill_youtube.py)
--   2026-09-24..09-30     -> trailing-7-day totals labelled with run date
--   from now on           -> one real calendar day per row ('day')
-- ------------------------------------------------------------
alter table youtube_video_analytics add column if not exists period_type text not null default 'day';
alter table youtube_traffic_sources add column if not exists period_type text not null default 'day';

update youtube_video_analytics set period_type = 'lifetime'    where period_date = '2026-09-23' and period_type = 'day';
update youtube_video_analytics set period_type = 'trailing_7d' where period_date between '2026-09-24' and '2026-09-30' and period_type = 'day';
update youtube_traffic_sources set period_type = 'lifetime'    where period_date = '2026-09-23' and period_type = 'day';
update youtube_traffic_sources set period_type = 'trailing_7d' where period_date between '2026-09-24' and '2026-09-30' and period_type = 'day';

do $$ begin
  alter table youtube_video_analytics drop constraint if exists youtube_video_analytics_video_id_period_date_key;
  alter table youtube_traffic_sources drop constraint if exists youtube_traffic_sources_video_id_period_date_traffic_source_key;
  if not exists (select 1 from pg_constraint where conname = 'youtube_video_analytics_video_period_type_key') then
    alter table youtube_video_analytics add constraint youtube_video_analytics_video_period_type_key
      unique (video_id, period_date, period_type);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'youtube_traffic_sources_video_period_type_src_key') then
    alter table youtube_traffic_sources add constraint youtube_traffic_sources_video_period_type_src_key
      unique (video_id, period_date, period_type, traffic_source_type);
  end if;
  alter table youtube_video_analytics drop constraint if exists youtube_video_analytics_period_type_chk;
  alter table youtube_video_analytics add constraint youtube_video_analytics_period_type_chk
    check (period_type in ('day','lifetime','trailing_7d'));
  alter table youtube_traffic_sources drop constraint if exists youtube_traffic_sources_period_type_chk;
  alter table youtube_traffic_sources add constraint youtube_traffic_sources_period_type_chk
    check (period_type in ('day','lifetime','trailing_7d'));
end $$;

comment on column youtube_video_analytics.period_type is
  'day = that calendar day only; lifetime = publish date..period_date; trailing_7d = legacy 9/24-9/30 2026 rows. Never sum across types.';
comment on column youtube_traffic_sources.period_type is
  'day = that calendar day only; lifetime = publish date..period_date; trailing_7d = legacy 9/24-9/30 2026 rows. Never sum across types.';

-- ------------------------------------------------------------
-- #14 updated_at / fetched_at never refreshed on upsert
-- ------------------------------------------------------------
create or replace function public.set_fetched_at()
returns trigger language plpgsql set search_path to '' as $f$
begin
  new.fetched_at := now();
  return new;
end; $f$;

drop trigger if exists trg_set_updated_at on youtube_video_stats;
create trigger trg_set_updated_at before update on youtube_video_stats
  for each row execute function public.set_updated_at();
drop trigger if exists trg_set_updated_at on youtube_video_analytics;
create trigger trg_set_updated_at before update on youtube_video_analytics
  for each row execute function public.set_updated_at();
drop trigger if exists trg_set_updated_at on youtube_traffic_sources;
create trigger trg_set_updated_at before update on youtube_traffic_sources
  for each row execute function public.set_updated_at();
drop trigger if exists trg_set_fetched_at on tiktok_video_metrics;
create trigger trg_set_fetched_at before update on tiktok_video_metrics
  for each row execute function public.set_fetched_at();
drop trigger if exists trg_set_fetched_at on podcast_episodes_megaphone;
create trigger trg_set_fetched_at before update on podcast_episodes_megaphone
  for each row execute function public.set_fetched_at();

-- ------------------------------------------------------------
-- #5 social_post_metrics: one row per post/metric/UTC day
-- Keeps the LATEST snapshot of each day (counters only grow; Stories'
-- second 12-hourly capture is the more complete one). Earlier same-day
-- snapshots are archived, not lost.
-- ------------------------------------------------------------
create table if not exists archive.social_post_metrics_intraday_20261022 (
  id bigint, post_id text, metric text, value numeric, fetched_at timestamptz, created_at timestamptz
);

with ranked as (
  select id, row_number() over (
           partition by post_id, metric, (fetched_at at time zone 'UTC')::date
           order by fetched_at desc, id desc) rn
    from social_post_metrics
)
insert into archive.social_post_metrics_intraday_20261022 (id, post_id, metric, value, fetched_at, created_at)
select m.id, m.post_id, m.metric, m.value, m.fetched_at, m.created_at
  from social_post_metrics m join ranked r on r.id = m.id where r.rn > 1;

with ranked as (
  select id, row_number() over (
           partition by post_id, metric, (fetched_at at time zone 'UTC')::date
           order by fetched_at desc, id desc) rn
    from social_post_metrics
)
delete from social_post_metrics m using ranked r where r.id = m.id and r.rn > 1;

alter table social_post_metrics
  add column if not exists fetched_date date
  generated always as ((fetched_at at time zone 'UTC')::date) stored;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'social_post_metrics_post_metric_day_key') then
    alter table social_post_metrics add constraint social_post_metrics_post_metric_day_key
      unique (post_id, metric, fetched_date);
  end if;
  alter table social_post_metrics drop constraint if exists social_post_metrics_post_id_metric_fetched_at_key;
end $$;

-- ------------------------------------------------------------
-- #6 Branded-content flag never set
-- Meta's API exposes no branded-content field for this account (tested
-- Sep 2026). Dani's posts carry FTC disclosure tags instead (#ad,
-- #sponsored, #<brand>partner), so flag from the caption and record that
-- the flag is caption-derived. Runs automatically for every new post.
-- ------------------------------------------------------------
alter table social_posts add column if not exists branded_detection text;
comment on column social_posts.branded_detection is
  'How is_branded_content was set: caption_disclosure = FTC tag in caption (#ad, #sponsored, #<brand>partner, paid partnership). NULL = not detected.';

create or replace function public.detect_branded_content()
returns trigger language plpgsql set search_path to '' as $f$
declare
  brand text;
begin
  if new.caption ~* '(#ad\M|#sponsored\M|#paidpartnership\M|#[a-z0-9]*partner\M|paid partnership)' then
    brand := (regexp_match(new.caption, '#([A-Za-z0-9]+)partner\M', 'i'))[1];
    if brand is null or brand = '' then
      brand := (regexp_match(new.caption, '@([A-Za-z0-9._]+)'))[1];
    end if;
    new.is_branded_content := true;
    new.branded_partner_name := coalesce(new.branded_partner_name, lower(brand));
    new.branded_detection := coalesce(new.branded_detection, 'caption_disclosure');
  elsif new.branded_detection = 'caption_disclosure' then
    -- caption edited and the disclosure removed
    new.is_branded_content := false;
    new.branded_partner_name := null;
    new.branded_detection := null;
  end if;
  return new;
end; $f$;

drop trigger if exists trg_detect_branded_content on social_posts;
create trigger trg_detect_branded_content before insert or update of caption on social_posts
  for each row execute function public.detect_branded_content();

update social_posts set caption = caption
 where caption ~* '(#ad\M|#sponsored\M|#paidpartnership\M|#[a-z0-9]*partner\M|paid partnership)';

-- ------------------------------------------------------------
-- #7 Airtable: status JSON text; bare-month dates
-- ------------------------------------------------------------
alter table airtable_partnerships
  add column if not exists month_committed_raw text,
  add column if not exists month_completed_raw text,
  add column if not exists month_committed_inferred date,
  add column if not exists month_completed_inferred date;

comment on column airtable_partnerships.month_committed_inferred is
  'month_committed if parseable; otherwise a bare month name ("June") resolved to the occurrence nearest the Airtable record createdTime. INFERRED -- use month_committed for strict reporting.';
comment on column airtable_partnerships.month_completed_inferred is
  'Same rule as month_committed_inferred, for Month Completed.';

update airtable_partnerships
   set status = (select string_agg(btrim(x), ', ') from jsonb_array_elements_text(status::jsonb) x)
 where status ~ '^\[.*\]$';

-- ------------------------------------------------------------
-- #8 affiliate_revenue is empty: platform affiliate revenue already lives
-- in QuickBooks. Expose it month x platform instead of a second copy.
-- LTK (RewardStyle) is its own labelled row per Katelyn's standing rule.
-- ------------------------------------------------------------
comment on table affiliate_revenue is
  'Legacy manual-CSV target, never populated. Use da_affiliate_platform_revenue_monthly (QuickBooks, booked) instead.';

create or replace view public.da_affiliate_platform_revenue_monthly
with (security_invoker = true) as
select date_trunc('month', txn_date)::date as month,
       case
         when account = 'Platform Affiliate:Platform Affiliate - LTK' then 'LTK (RewardStyle)'
         when account = 'Amazon Platform Affiliate Revenue'           then 'Amazon'
         when account = 'Facebook Platform Affiliate Commission'      then 'Facebook'
         when account = 'TikTok Platform Affiliate Commission'        then 'TikTok'
         when account = 'Platform Affiliate:Platform Affiliate - Other' then 'Other platform'
       end as platform,
       sum(amount) as booked_revenue,
       count(*)    as lines
  from qb_da_transaction_lines
 where category = 'income'
   and account in ('Platform Affiliate:Platform Affiliate - LTK', 'Amazon Platform Affiliate Revenue',
                   'Facebook Platform Affiliate Commission', 'TikTok Platform Affiliate Commission',
                   'Platform Affiliate:Platform Affiliate - Other')
 group by 1, 2;
comment on view public.da_affiliate_platform_revenue_monthly is
  'Booked platform-affiliate revenue from QuickBooks, month x platform. Recent months are directional (Amazon ~45-50 day lag, LTK ~90 day true-up).';
revoke all on public.da_affiliate_platform_revenue_monthly from anon, authenticated;

-- ------------------------------------------------------------
-- #9 TikTok identity mapping
-- ------------------------------------------------------------
update social_account_identity
   set api_account_id = '-000K2C4dnrBsCwG9bthaxx0wNWEOFKEBVbM',
       notes = 'API id = TikTok token open_id (business_organic OAuth, live since Sep 2026). Social Blade id kept for the daily Social Blade series.'
 where platform = 'tiktok' and api_account_id is null;

delete from social_accounts sa
 where sa.platform = 'tiktok' and coalesce(btrim(sa.account_id), '') = ''
   and not exists (select 1 from social_metrics m where m.account_id = sa.account_id)
   and not exists (select 1 from social_posts p where p.account_id = sa.account_id)
   and not exists (select 1 from social_audience_demographics d where d.account_id = sa.account_id);

-- ------------------------------------------------------------
-- #16 Housekeeping: unused index
-- ------------------------------------------------------------
drop index if exists idx_airtable_platform;

-- ------------------------------------------------------------
-- #15 Migration history: record this and every later migration
-- (the sql/ folder is the history for 001-034; see README).
-- ------------------------------------------------------------
create table if not exists public.da_schema_migrations (
  version text primary key,
  description text,
  applied_at timestamptz not null default now()
);
alter table public.da_schema_migrations enable row level security;
revoke all on public.da_schema_migrations from anon, authenticated;

-- 001-034 were applied by hand before tracking existed: record them as a
-- baseline so the migrations workflow never re-runs them.
insert into public.da_schema_migrations (version, description)
select lpad(g::text, 3, '0'), 'baseline -- applied before migration tracking (Oct 2026)'
  from generate_series(1, 34) g
on conflict (version) do nothing;

insert into public.da_schema_migrations (version, description)
values ('035', 'Oct 21 2026 bug list fixes + daily health sweep')
on conflict (version) do nothing;

commit;

-- ============================================================
-- Daily health sweep (separate transaction so a typo here can't roll
-- back the fixes above)
-- ============================================================
begin;

create table if not exists public.da_health_sweep_log (
  id bigint generated always as identity primary key,
  run_at timestamptz not null default now(),
  check_id text not null,
  severity text not null,
  status text not null,          -- PASS | WARN | FAIL
  detail text,
  value numeric
);
alter table public.da_health_sweep_log enable row level security;
revoke all on public.da_health_sweep_log from anon, authenticated;
create index if not exists idx_health_sweep_log_run on public.da_health_sweep_log (run_at desc, check_id);

create or replace view public.da_health_sweep with (security_invoker = true) as
with
fresh as (
  select * from (values
    ('fresh_qb_lines',        'High',   (select max(updated_at)          from qb_da_transaction_lines)::timestamptz, 2,  'QuickBooks sync (daily)'),
    ('fresh_ar_snapshot',     'High',   (select max(snapshot_date)       from qb_da_invoices_daily_snapshot)::timestamptz, 2, 'AR daily snapshot'),
    ('fresh_cash',            'High',   (select max(as_of)               from da_cash_current_balance)::timestamptz, 2, 'Brex/PayPal/Plaid balances'),
    ('fresh_airtable',        'Medium', (select max(updated_at)          from airtable_partnerships)::timestamptz, 3, 'Airtable partnerships'),
    ('fresh_meta',            'High',   (select max(period_date) from social_metrics where source = 'api' and account_id not like '-000%')::timestamptz, 2, 'Meta account metrics'),
    ('fresh_tiktok',          'High',   (select max(period_date) from social_metrics where account_id = '-000K2C4dnrBsCwG9bthaxx0wNWEOFKEBVbM')::timestamptz, 2, 'TikTok account metrics'),
    ('fresh_social_blade',    'Medium', (select max(period_date) from social_metrics where source <> 'api')::timestamptz, 3, 'Social Blade'),
    ('fresh_post_metrics',    'Medium', (select max(fetched_at)          from social_post_metrics), 2, 'Post-level metrics (12-hourly)'),
    ('fresh_tiktok_videos',   'Medium', (select max(fetched_at)          from tiktok_video_metrics), 2, 'TikTok per-video'),
    ('fresh_youtube_stats',   'Medium', (select max(updated_at)          from youtube_video_stats), 2, 'YouTube public stats'),
    ('fresh_youtube_analytics','High',  (select max(period_date) from youtube_video_analytics where period_type = 'day')::timestamptz, 5, 'YouTube Analytics (OAuth; data lags 1-3 days)'),
    ('fresh_youtube_traffic', 'High',   (select max(period_date) from youtube_traffic_sources where period_type = 'day')::timestamptz, 5, 'YouTube traffic sources'),
    ('fresh_podcast_metrics', 'High',   (select max(period_date)         from podcast_metrics)::timestamptz, 7, 'Podstock pull'),
    ('fresh_podcast_episodes','High',   (select max(fetched_at)          from podcast_episodes_megaphone), 2, 'Megaphone episode metadata'),
    ('fresh_podcast_downloads','Medium',(select max(day)                 from podcast_episode_daily_downloads)::timestamptz, 14, 'Megaphone per-episode downloads (manual export)'),
    ('fresh_earned_mentions', 'Medium', (select max(created_at)          from earned_mentions), 8, 'Xpoz weekly (Mondays)')
  ) v(check_id, severity, latest, max_days, label)
),
checks as (
  -- Freshness
  select check_id, severity,
         case when latest is null then 'FAIL'
              when now() - latest > make_interval(days => max_days) then 'FAIL' else 'PASS' end as status,
         label || ': latest ' || coalesce(to_char(latest at time zone 'UTC', 'YYYY-MM-DD HH24:MI'), 'never')
               || ' UTC (allowed ' || max_days || 'd)' as detail,
         round(extract(epoch from now() - latest) / 86400.0, 1) as value
    from fresh

  -- #1 / regression guard: balance-sheet accounts leaking into the P&L
  union all
  select 'prepaid_in_operating_pnl', 'Critical',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'Prepaid% rows in da_pnl_operating (must be 0)', count(*)
    from da_pnl_operating where account ilike 'Prepaid%'
  union all
  select 'non_operating_drift', 'Critical',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'Lines on Non-Operating-mapped accounts not tagged non_operating', count(*)
    from qb_da_transaction_lines t join qb_account_business_unit_map m on m.account_name = t.account
   where m.business_unit = 'Non-Operating' and (t.category <> 'non_operating' or t.source <> 'Non-Operating')
  union all
  select 'agency_fee_category', 'High',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'Agency Fee / Podcast Agency Fee lines not tagged expense', count(*)
    from qb_da_transaction_lines where account in ('Agency Fee','Podcast Agency Fee') and category <> 'expense'
  union all
  select 'unmapped_qb_accounts', 'Medium',
         case when count(distinct account) = 0 then 'PASS' else 'FAIL' end,
         coalesce('Unmapped: ' || string_agg(distinct account, '; '), 'All accounts mapped'), count(distinct account)
    from qb_da_transaction_lines t
   where not exists (select 1 from qb_account_business_unit_map m where m.account_name = t.account)
  union all
  select 'needs_review_lines', 'Medium',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         'Lines with source = needs_review, $' || coalesce(round(sum(amount))::text, '0'), count(*)
    from qb_da_transaction_lines where source = 'needs_review'
  union all
  select 'employee_401k_nets_to_zero', 'Medium',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         coalesce('Non-zero closed years: ' || string_agg(y || ' $' || round(bal, 2), '; ' order by y), 'All closed years net to $0'),
         count(*)
    from (select extract(year from txn_date)::int y, sum(amount) bal
            from qb_da_transaction_lines
           where account = 'Payroll:Retirement Plan Contributions - Employee'
             and txn_date < date_trunc('year', now())
           group by 1 having abs(sum(amount)) > 0.01) z

  -- #3 TikTok zeros
  union all
  select 'tiktok_fake_zero_engagement', 'High',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'TikTok api views/likes/comments/shares = 0 in last 7 days', count(*)
    from social_metrics
   where account_id = '-000K2C4dnrBsCwG9bthaxx0wNWEOFKEBVbM' and source = 'api'
     and metric in ('views','likes','comments','shares') and value = 0
     and period_date >= current_date - 7

  -- #5 duplicates
  union all
  select 'post_metric_same_day_dupes', 'Medium',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'post_id/metric/day groups with >1 row', count(*)
    from (select 1 from social_post_metrics group by post_id, metric, (fetched_at at time zone 'UTC')::date having count(*) > 1) d

  -- #6 branded content
  union all
  select 'branded_posts_flagged', 'Medium',
         case when count(*) > 0 then 'PASS' else 'FAIL' end,
         'Posts flagged is_branded_content', count(*)
    from social_posts where is_branded_content

  -- #7 Airtable
  union all
  select 'airtable_status_json_text', 'Medium',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'Status stored as JSON-array text', count(*)
    from airtable_partnerships where status like '[%'
  union all
  select 'airtable_status_unknown', 'Low',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         'Deals with empty Status in Airtable (ask Jennifer/Katelyn to fill in)', count(*)
    from airtable_partnerships where status = 'Unknown'
  union all
  select 'airtable_net_gt_gross', 'Medium',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         coalesce('Net > gross: ' || string_agg(deal_id, ', '), 'none'), count(*)
    from airtable_partnerships where net_amt > gross_amt
  union all
  select 'airtable_far_future_dates', 'Medium',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         coalesce('Month > 2 yrs out: ' || string_agg(deal_id || ' (' || greatest(month_committed, month_completed)::text || ')', ', '), 'none'), count(*)
    from airtable_partnerships
   where greatest(month_committed, month_completed) > (current_date + interval '2 years')
  union all
  select 'airtable_month_committed_missing', 'Low',
         case when count(*) filter (where month_committed_inferred is null and month_committed_raw is not null) = 0 then 'PASS' else 'WARN' end,
         'Deals with Month Committed text that could not be resolved even by inference',
         count(*) filter (where month_committed_inferred is null and month_committed_raw is not null)
    from airtable_partnerships

  -- #9 identity
  union all
  select 'social_identity_complete', 'Medium',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'Platforms in social_account_identity missing api_account_id', count(*)
    from social_account_identity where api_account_id is null and platform in ('instagram','facebook','tiktok')
  union all
  select 'social_accounts_blank_ids', 'Low',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         'social_accounts rows with blank account_id', count(*)
    from social_accounts where coalesce(btrim(account_id), '') = ''

  -- #13 secrets
  union all
  select 'qb_token_plaintext', 'Low',
         case when count(*) = 0 then 'PASS' else 'WARN' end,
         'QuickBooks refresh token still in public.qb_oauth_credentials (apply migration 036 after code push)', count(*)
    from qb_oauth_credentials where coalesce(refresh_token, '') <> ''

  -- Security regression guard (Oct 7 lockdown)
  union all
  select 'rls_disabled_tables', 'Critical',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         coalesce('RLS off: ' || string_agg(c.relname, ', '), 'All public tables have RLS'), count(*)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
  union all
  select 'anon_readable_objects', 'Critical',
         case when count(*) = 0 then 'PASS' else 'FAIL' end,
         coalesce('anon can read: ' || string_agg(c.relname, ', '), 'Only earned_mentions is anon-readable'), count(*)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relkind in ('r','v','m')
     and has_table_privilege('anon', c.oid, 'select')
     and c.relname <> 'earned_mentions'
     and (c.relkind <> 'r' or exists (select 1 from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname
                                       and ('anon' = any(p.roles) or 'public' = any(p.roles))))
)
select check_id, severity, status, detail, value, now() as checked_at
  from checks
 order by case status when 'FAIL' then 0 when 'WARN' then 1 else 2 end,
          case severity when 'Critical' then 0 when 'High' then 1 when 'Medium' then 2 else 3 end,
          check_id;

comment on view public.da_health_sweep is
  'Live data-health checks (bug list Oct 21 2026 + regression guards). Read-only. Logged daily via select public.da_record_health_sweep().';
revoke all on public.da_health_sweep from anon, authenticated;

-- One call records a snapshot of the sweep so day-over-day changes are visible.
create or replace function public.da_record_health_sweep()
returns integer language plpgsql security definer set search_path to '' as $f$
declare n integer;
begin
  insert into public.da_health_sweep_log (check_id, severity, status, detail, value)
  select check_id, severity, status, detail, value from public.da_health_sweep;
  get diagnostics n = row_count;
  return n;
end; $f$;
revoke all on function public.da_record_health_sweep() from public, anon, authenticated;

commit;
