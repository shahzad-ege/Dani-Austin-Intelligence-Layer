-- ============================================================
-- Migration 005: Post-level analytics + engagement rate formulas
-- ============================================================

-- ITEM 4: engagement rate.
--
-- HOUSE DEFINITION (decided): engagement_rate_pct = interactions / reach.
-- Measures response among unique people who ACTUALLY SAW the content,
-- rather than against a follower count including inactive accounts (DA has
-- 2.49M followers but reaches ~500-800K daily), or against views, which
-- counts repeat views from the same person.
--
-- Noted honestly: this is also the highest of the three. Chosen for being
-- the sound measure, not the flattering one -- worth stating rather than
-- quietly benefiting from the coincidence.
--
-- EXCEPTION: brand buyers benchmark against the FOLLOWER-based convention.
-- Use er_vs_followers_pct, explicitly labelled, in negotiation contexts.
-- All three remain available; the spread between them on identical data is
-- ~9.5x, so never compare figures computed on different denominators.
--   vs_followers : prevailing convention in brand-deal contexts
--   vs_reach     : most defensible analytically (response among people who
--                  actually saw it)
--   vs_views     : most conservative
-- Built on social_metrics_complete_days -- partial current-day rows would
-- badly distort all three.
drop view if exists da_social_engagement_rate;

create view da_social_engagement_rate as
with m as (
  select
    account_id, period_date,
    max(value) filter (where metric = 'total_interactions') as interactions,
    max(value) filter (where metric = 'followers') as followers,
    max(value) filter (where metric = 'reach') as reach,
    max(value) filter (where metric = 'views') as views
  from social_metrics_complete_days
  where source = 'api'
  group by account_id, period_date
)
select
  sa.platform, sa.handle, m.period_date,
  -- CANONICAL: quote this when asked for "engagement rate" unqualified.
  round((m.interactions / nullif(m.reach, 0)) * 100, 4) as engagement_rate_pct,
  round((m.interactions / nullif(m.followers, 0)) * 100, 4) as er_vs_followers_pct,
  round((m.interactions / nullif(m.reach, 0)) * 100, 4) as er_vs_reach_pct,
  round((m.interactions / nullif(m.views, 0)) * 100, 4) as er_vs_views_pct,
  m.interactions, m.followers, m.reach, m.views
from m
join social_accounts sa on sa.account_id = m.account_id
where m.interactions is not null;

alter view da_social_engagement_rate set (security_invoker = true);

-- ITEMS 5 + 6 + Facebook post-level + Stories.
-- One shared schema across all platforms -- the shape is genuinely the same
-- (a post, and metrics about it over time).
create table if not exists social_posts (
  id bigint generated always as identity primary key,
  account_id text not null references social_accounts(account_id),
  post_id text not null,
  platform text not null,
  media_type text,
  caption text,
  permalink text,
  posted_at timestamptz,
  -- Instagram branded-content tagging: the direct programmatic link between
  -- a post and Brand Partnership revenue. Better attribution than the
  -- manual Airtable deliverable_platform path.
  is_branded_content boolean default false,
  branded_partner_name text,
  -- Stories expire at 24h and their insights vanish PERMANENTLY. Flagged
  -- because a missing story is unrecoverable, not retryable.
  is_ephemeral boolean default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account_id, post_id)
);

create index if not exists idx_social_posts_posted_at on social_posts (posted_at desc);
create index if not exists idx_social_posts_platform on social_posts (platform);
create index if not exists idx_social_posts_branded on social_posts (is_branded_content) where is_branded_content = true;

create table if not exists social_post_metrics (
  id bigint generated always as identity primary key,
  post_id text not null,
  metric text not null,
  value numeric(18,4) not null,
  fetched_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (post_id, metric, fetched_at)
);

create index if not exists idx_social_post_metrics_lookup on social_post_metrics (post_id, metric);

alter table social_posts enable row level security;
alter table social_post_metrics enable row level security;

-- "Top posts" is DERIVED, never stored as a flag.
create or replace view social_top_posts as
with latest as (
  select distinct on (post_id, metric) post_id, metric, value
  from social_post_metrics
  order by post_id, metric, fetched_at desc
)
select
  sp.platform, sp.post_id, sp.media_type, sp.caption, sp.permalink,
  sp.posted_at, sp.is_branded_content, sp.branded_partner_name,
  max(l.value) filter (where l.metric = 'views') as views,
  max(l.value) filter (where l.metric = 'reach') as reach,
  max(l.value) filter (where l.metric = 'likes') as likes,
  max(l.value) filter (where l.metric = 'comments') as comments,
  max(l.value) filter (where l.metric = 'shares') as shares,
  max(l.value) filter (where l.metric = 'saved') as saved,
  max(l.value) filter (where l.metric = 'total_interactions') as total_interactions,
  -- Which content actually GREW the audience, vs merely got liked
  max(l.value) filter (where l.metric = 'follows') as follows_driven,
  max(l.value) filter (where l.metric = 'profile_visits') as profile_visits,
  -- Short-form video retention (TikTok's dominant algorithmic signal)
  max(l.value) filter (where l.metric = 'full_video_watched_rate') as completion_rate,
  max(l.value) filter (where l.metric = 'average_time_watched') as avg_time_watched,
  max(l.value) filter (where l.metric = 'reels_skip_rate') as reels_skip_rate,
  -- Story navigation
  max(l.value) filter (where l.metric = 'exits') as story_exits,
  max(l.value) filter (where l.metric = 'taps_forward') as story_taps_forward,
  max(l.value) filter (where l.metric = 'taps_back') as story_taps_back
from social_posts sp
join latest l on l.post_id = sp.post_id
group by sp.platform, sp.post_id, sp.media_type, sp.caption, sp.permalink,
         sp.posted_at, sp.is_branded_content, sp.branded_partner_name;

alter view social_top_posts set (security_invoker = true);

-- The branded-content -> revenue bridge.
create or replace view social_branded_content_performance as
select
  platform, branded_partner_name,
  count(*) as post_count,
  sum(views) as total_views,
  sum(reach) as total_reach,
  sum(total_interactions) as total_interactions,
  sum(follows_driven) as total_follows_driven,
  min(posted_at) as first_post,
  max(posted_at) as last_post
from social_top_posts
where is_branded_content = true
group by platform, branded_partner_name;

alter view social_branded_content_performance set (security_invoker = true);
