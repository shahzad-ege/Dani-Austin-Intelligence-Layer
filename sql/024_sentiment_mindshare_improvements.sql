-- ============================================================
-- Migration 024: Six real improvements to sentiment/mindshare analysis (Sep 2026)
-- ============================================================

-- 1. is_substantive fix: was missing from COWORK_SENTIMENT_TASK.md
-- entirely, meaning anything Cowork scored defaulted to true. Fixed in
-- the task description (not a schema change).

-- 2. Xpoz force_latest + Reddit sort=new: real finding, confirmed
-- across 2 real weeks -- Reddit returned 0 genuinely-new results out
-- of 100 touched, both weeks. Confirmed via the real installed SDK
-- that force_latest exists on all 4 platforms; Reddit additionally
-- supports sort. Applied in xpoz_connector.py. NOT YET LIVE-VERIFIED --
-- treat the next real sync's genuinely_new numbers as confirmation.

-- 3. Topic tagging.
alter table earned_mentions add column if not exists topic text;
alter table earned_mentions add constraint earned_mentions_topic_check
  check (topic is null or topic in (
    'press_coverage', 'business_brand', 'personal_family',
    'birth_parenting_criticism', 'authenticity_accusations',
    'appropriation_business_ethics', 'political_labeling',
    'wealth_lifestyle_envy', 'routine_administrative',
    'name_collision', 'other'
  ));
-- All 275 existing rows backfilled by re-reading each mention's
-- content and existing sentiment_reasoning. Real finding:
-- authenticity_accusations is the dominant driver of negative
-- sentiment (40 mentions, 70% negative) -- far ahead of birth/
-- parenting criticism (60%) or wealth envy (100% of only 3 mentions).

-- 4. Name-collision automated filtering: investigated real Xpoz
-- parameters (author_username/author_id/language on Twitter). NOT
-- applied -- language filtering risks cutting real non-English
-- coverage (confirmed real Portuguese/Spanish press coverage exists
-- in this data already). No clean automated fix available without
-- risking false negatives; manual judgment remains the right approach.

create view da_mention_topics
with (security_invoker = true)
as
select
  topic,
  count(*) as mentions,
  count(*) filter (where sentiment = 'negative') as negative_count,
  round(100.0 * count(*) filter (where sentiment = 'negative') / count(*), 0) as pct_negative,
  sum(like_count + comment_count + share_count) as total_engagement
from earned_mentions
where is_substantive and topic is not null
group by topic
order by negative_count desc;

-- 5. Week-over-week delta view.
create view da_mindshare_sentiment_weekly_delta
with (security_invoker = true)
as
select
  curr.week_start,
  curr.platform,
  curr.substantive_mentions,
  curr.substantive_mentions - lag(curr.substantive_mentions) over w as mentions_change,
  curr.pct_positive,
  curr.pct_positive - lag(curr.pct_positive) over w as pct_positive_change,
  curr.pct_negative,
  curr.pct_negative - lag(curr.pct_negative) over w as pct_negative_change,
  curr.genuinely_new,
  curr.total_touched,
  round(100.0 * curr.genuinely_new / nullif(curr.total_touched, 0), 0) as pct_genuinely_new
from da_mindshare_sentiment_weekly curr
window w as (partition by curr.platform order by curr.week_start)
order by curr.week_start, curr.platform;

-- 6. Reddit budget reallocation: NOT acted on. One data point (0%
-- genuinely-new) is not enough to justify a budget change -- could be
-- a real, stable pattern or could be an artifact the force_latest/
-- sort=new fix above resolves entirely. Revisit after 3-4 more real
-- weeks, once the fix's actual effect is known.

-- ============================================================
-- Addendum: Social Blade deep-history capability (Sep 2026)
-- ============================================================
-- No schema change -- documented here for the record. Confirmed
-- directly from Social Blade's own official API schema
-- (socialblade.com/developers/docs): the ~30-day daily[] array cap has
-- nothing to do with subscription tier. It's controlled by a `history`
-- request parameter this connector never sent. Real confirmed depths:
-- default=30 days/1cr, extended=1yr/2cr, archive=3yr/3cr,
-- vault=10yr/5cr (TikTok/IG/FB; YouTube caps at 3yr via archive).
--
-- fetch_statistics() now accepts an optional history parameter
-- (defaults to None, verified unchanged existing behavior). A new
-- deep_history_backfill() function exists for a deliberate one-time
-- deeper pull, requiring explicit confirm_cost=True so it can never be
-- triggered accidentally by routine automation. Real cost: a full
-- 10-year pull across all 3 accounts (Instagram, TikTok, Facebook) is
-- 15 credits -- 3 months of Silver's 5-credit/month allowance. Not yet
-- run against the real API -- this is a deliberate spending decision,
-- pending a real choice on how much history is worth the cost.
