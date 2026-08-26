-- ============================================================
-- Migration 010: Account deduplication + branded content investigation
-- ============================================================

-- FINDING 1: the reported "Facebook post-level dedup issue" was NOT a bug.
-- social_post_metrics had 375 rows for 25 Facebook posts (15 per post), but
-- inspection showed those are 15 separate sync runs capturing REAL change
-- over time (e.g. one post's 'like' count: 416 -> 417 -> 418 -> 419 across
-- Aug 20-26). That's the intended time-series design, and social_top_posts
-- already correctly deduplicates via `distinct on (post_id, metric) order by
-- fetched_at desc`. No fix needed.

-- FINDING 2: there IS a real duplicate-account issue, just not where
-- expected. Two social_accounts rows exist per platform -- Meta's connector
-- seeds real numeric IDs (e.g. '498279563591307'), Social Blade's seeds
-- synthetic ones (e.g. 'daniaustin_fb'). Keeping both is DELIBERATE (it's
-- what enables the cross-source verification this project relies on; the two
-- currently agree to within 0.001%). The danger is that naively summing
-- followers across social_accounts double-counts every platform: ~5.26M
-- instead of the real ~3.76M.

-- Remove an orphan row: the TikTok connector seeded an account with an EMPTY
-- account_id before it had real credentials. Confirmed zero dependent rows
-- in social_metrics or social_posts before deleting.
delete from social_accounts where account_id = '';

-- Fix a stale handle: Social Blade's row correctly had 'daniaustinofficial'
-- (the real vanity slug, discovered when its 404 was fixed), but the Meta
-- connector had seeded 'daniaustin' from the earlier wrong assumption and
-- never updated it.
update social_accounts set handle = 'daniaustinofficial'
where account_id = '498279563591307';

-- THE ACTUAL FIX: a deduplicated followers view. Prefers first-party 'api'
-- data, falls back to 'social_blade' only where no API data exists (TikTok).
-- Built on social_metrics_complete_days so partial current-day rows can't
-- distort it. USE THIS for any total-audience or per-platform follower
-- question rather than joining social_metrics to social_accounts directly.
create or replace view social_followers_deduped as
with ranked as (
  select
    sa.platform,
    sa.handle,
    sm.value as followers,
    sm.period_date,
    sm.source,
    row_number() over (
      partition by sa.platform, sm.period_date
      order by case when sm.source = 'api' then 0 else 1 end
    ) as source_priority
  from social_metrics_complete_days sm
  join social_accounts sa on sa.account_id = sm.account_id
  where sm.metric = 'followers'
)
select platform, handle, followers, period_date, source
from ranked
where source_priority = 1;

alter view social_followers_deduped set (security_invoker = true);

-- FINDING 3: branded content tagging is empty because the connector NEVER
-- REQUESTED any branded-content field from the API. meta_connector.py's
-- media request asks only for
-- "id,caption,media_type,permalink,timestamp,like_count,comments_count" --
-- so is_branded_content gets the schema default (false) on every row and
-- branded_partner_name is always null. The model columns and the project
-- instructions both describe the feature, but the API request was never
-- updated to match.
--
-- NOT fixed by guessing a field name -- this project has already lost
-- several cycles to guessed Meta/QuickBooks field names. Instead,
-- connectors/discover_branded_content_fields.py tests 14 candidate field
-- names against the live API one at a time and reports which are accepted,
-- which are silently omitted, and which are rejected outright. Run that,
-- then update the connector with whatever actually works.
