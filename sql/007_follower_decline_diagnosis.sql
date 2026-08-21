-- ============================================================
-- Migration 007: Follower-decline diagnosis views
-- ============================================================

-- Day-over-day follower change, built on social_metrics_complete_days
-- (never the partial current day) so a delta is never distorted by an
-- incomplete capture.
create or replace view social_daily_follower_change as
select
  sa.platform,
  sa.handle,
  sm.period_date,
  sm.value as followers,
  sm.value - lag(sm.value) over (partition by sm.account_id order by sm.period_date) as net_change
from social_metrics_complete_days sm
join social_accounts sa on sa.account_id = sm.account_id
where sm.metric = 'followers' and sm.source = 'api';

alter view social_daily_follower_change set (security_invoker = true);

-- The actual diagnosis: publishing activity vs. follower trend per day.
-- follows_driven is each post's LIFETIME cumulative attributed-follow
-- count, joined here against the day the post was PUBLISHED -- shows
-- correlation with the follower trend, not a literal same-day causal count.
create or replace view social_posts_vs_follower_change as
select
  d.platform,
  d.period_date,
  d.followers,
  d.net_change,
  count(p.post_id) as posts_published_that_day,
  coalesce(sum(tp.follows_driven), 0) as cumulative_follows_from_that_days_posts,
  string_agg(p.media_type, ', ') as media_types_published
from social_daily_follower_change d
left join social_posts p
  on p.platform = d.platform
 and p.posted_at::date = d.period_date
 and p.is_ephemeral = false  -- Stories excluded: not comparable to feed/Reel growth
left join social_top_posts tp on tp.post_id = p.post_id
group by d.platform, d.period_date, d.followers, d.net_change
order by d.platform, d.period_date;

alter view social_posts_vs_follower_change set (security_invoker = true);
