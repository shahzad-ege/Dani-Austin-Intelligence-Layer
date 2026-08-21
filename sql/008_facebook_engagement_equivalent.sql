-- ============================================================
-- Migration 008: Facebook engagement-rate equivalent
-- ============================================================
--
-- Prompted by a real DA Claude Project response correctly flagging that
-- it couldn't compute a Facebook engagement % using the house formula,
-- since Facebook has no working "reach" metric currently
-- (page_impressions_unique confirmed dead by the live API).
--
-- Facebook DOES have real analogues to Instagram's total_interactions and
-- views: page_post_engagements and page_media_view respectively. These are
-- NOT the same underlying concept as Instagram's metrics -- close enough
-- to be directionally useful, not identical enough to treat as the same
-- metric. er_vs_reach_pct stays genuinely NULL for Facebook, not
-- approximated -- a real data gap (no reach-equivalent metric available),
-- not a SQL gap.
--
-- Verified against real data: Facebook's Aug 18 er_vs_followers_pct
-- (6.1588%) matches the manually-computed figure from the original
-- social-analytics study almost exactly.

drop view if exists da_social_engagement_rate;

create view da_social_engagement_rate as
with ig as (
  select
    account_id, period_date,
    max(value) filter (where metric = 'total_interactions') as interactions,
    max(value) filter (where metric = 'followers') as followers,
    max(value) filter (where metric = 'reach') as reach,
    max(value) filter (where metric = 'views') as views
  from social_metrics_complete_days
  where source = 'api'
  group by account_id, period_date
),
fb as (
  select
    account_id, period_date,
    max(value) filter (where metric = 'page_post_engagements') as interactions,
    max(value) filter (where metric = 'followers') as followers,
    max(value) filter (where metric = 'page_media_view') as views
  from social_metrics_complete_days
  where source = 'api'
  group by account_id, period_date
)
select
  sa.platform, sa.handle, ig.period_date,
  round((ig.interactions / nullif(ig.reach, 0)) * 100, 4) as engagement_rate_pct,
  round((ig.interactions / nullif(ig.followers, 0)) * 100, 4) as er_vs_followers_pct,
  round((ig.interactions / nullif(ig.reach, 0)) * 100, 4) as er_vs_reach_pct,
  round((ig.interactions / nullif(ig.views, 0)) * 100, 4) as er_vs_views_pct,
  ig.interactions, ig.followers, ig.reach, ig.views
from ig
join social_accounts sa on sa.account_id = ig.account_id
where ig.interactions is not null

union all

select
  sa.platform, sa.handle, fb.period_date,
  null as engagement_rate_pct,
  round((fb.interactions / nullif(fb.followers, 0)) * 100, 4) as er_vs_followers_pct,
  null as er_vs_reach_pct,
  round((fb.interactions / nullif(fb.views, 0)) * 100, 4) as er_vs_views_pct,
  fb.interactions, fb.followers, null as reach, fb.views
from fb
join social_accounts sa on sa.account_id = fb.account_id
where fb.interactions is not null;

alter view da_social_engagement_rate set (security_invoker = true);
