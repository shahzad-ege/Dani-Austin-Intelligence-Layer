-- ============================================================
-- Migration 022: "Check and fix everything" - second regression pass
-- ============================================================

-- FIX 1: Facebook demographics date off-by-one, confirmed via Meta's
-- own documented example. Real production impact: 90 rows had landed
-- dated one day in the future. See meta_connector.py for the full fix
-- (subtracts 1 day, converting UTC end_time to the Pacific-time day
-- the data actually describes).
update social_audience_demographics
set period_date = period_date - interval '1 day'
where account_id = '498279563591307';

-- FIX 2: RLS policies added to 26 of the 27 flagged tables (internal
-- SELECT/UPDATE/INSERT for anon+authenticated, matching earned_mentions'
-- established pattern).
--
-- qb_oauth_credentials was DELIBERATELY EXCLUDED after checking its real
-- columns: it holds a genuine refresh_token secret. Granting anon/
-- authenticated read access to a real OAuth token is a real exposure
-- risk, not the same "internal admin table" pattern the others fit --
-- confirmed by checking column names before applying the blanket policy,
-- not assumed. This table correctly remains service-role-only.
do $$
declare
  t text;
  tables text[] := array[
    'affiliate_commission_deals','affiliate_revenue','airtable_partnerships',
    'da_budget_actual_pnl','da_cash_current_balance','da_cash_flow_forecast',
    'da_cash_flow_monthly_actuals','da_cash_flow_recurring_assumptions',
    'da_entity_summary','da_revenue_forecast','da_scenario_cash_reference',
    'da_scenario_pnl_reference','podcast_ad_bookings','podcast_audience_demographics',
    'podcast_metrics','podcast_top_episode_snapshots','qb_account_business_unit_map',
    'qb_da_invoices','qb_da_invoices_daily_snapshot','qb_da_transaction_lines',
    'social_account_identity','social_accounts','social_audience_demographics',
    'social_metrics','social_post_metrics','social_posts'
  ];
begin
  foreach t in array tables loop
    execute format('create policy "internal_tools_select" on %I for select to anon, authenticated using (true)', t);
    execute format('create policy "internal_tools_update" on %I for update to anon, authenticated using (true) with check (true)', t);
    execute format('create policy "internal_tools_insert" on %I for insert to anon, authenticated with check (true)', t);
  end loop;
end $$;

-- FIX 3: da_pnl_operating -- safe-by-default companion view that
-- pre-excludes non_operating rows, so the safe path is the default
-- rather than relying on a written instruction.
create view da_pnl_operating
with (security_invoker = true)
as
select month, account, category, amount
from da_pnl
where category != 'non_operating';
