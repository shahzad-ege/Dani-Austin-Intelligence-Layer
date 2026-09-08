-- ============================================================
-- Migration 020: Sentiment scoring for earned_mentions
-- ============================================================
--
-- Closes the sentiment gap accepted when Xpoz (free, raw mentions) was
-- chosen over paid tools like Brand24/Awario that include sentiment
-- built in. Scored via sentiment_scorer.py, batching mentions into
-- Claude calls rather than one call per mention.
alter table earned_mentions add column if not exists sentiment text;
alter table earned_mentions add column if not exists sentiment_reasoning text;
alter table earned_mentions add constraint earned_mentions_sentiment_check
  check (sentiment is null or sentiment in ('positive', 'negative', 'neutral', 'mixed'));

-- Combined mindshare + sentiment view, by platform per week.
-- Real limitation as of Sep 2026: only 2 days of data exist (manual
-- test runs), not real weekly history. Also note: mention volume
-- reflects Xpoz's rolling 60-day re-scan behavior -- most mentions in
-- any pull are re-discovered posts with refreshed engagement, not new
-- content (confirmed: one pull touched 190 rows, only 16 genuinely new).
create or replace view da_mindshare_sentiment_weekly as
select
  date_trunc('week', fetched_at)::date as week_start,
  platform,
  count(*) as mentions,
  round(100.0 * count(*) filter (where sentiment = 'positive') / count(*), 0) as pct_positive,
  round(100.0 * count(*) filter (where sentiment = 'negative') / count(*), 0) as pct_negative,
  round(100.0 * count(*) filter (where sentiment = 'neutral') / count(*), 0) as pct_neutral,
  round(100.0 * count(*) filter (where sentiment = 'mixed') / count(*), 0) as pct_mixed
from earned_mentions
where sentiment is not null
group by week_start, platform
order by week_start, platform;

-- Real bug found and fixed during Cowork automation testing (Sep 2026):
-- RLS was enabled on earned_mentions (relrowsecurity=true) but ZERO
-- policies existed -- meaning every role except service_role was
-- silently denied ALL access. This caused the Cowork scheduled task
-- (which connects via anon/authenticated, not the service_role key
-- Claude's own direct Supabase access uses) to report "no unscored
-- rows" even though 3 real test rows with sentiment=null genuinely
-- existed at the time. Confirmed via pg_class.relrowsecurity and an
-- empty pg_policies result before this fix.
create policy "internal_tools_select" on earned_mentions
  for select
  to anon, authenticated
  using (true);

create policy "internal_tools_update" on earned_mentions
  for update
  to anon, authenticated
  using (true)
  with check (true);

-- Three real analysis tweaks requested (Sep 2026):
-- 1. genuinely_new vs total_touched -- distinguishes new discoveries
--    from re-scanned/re-discovered posts. NOTE: shows 100% new right
--    now since this is the first week of data collection -- becomes
--    meaningful starting week 2, once some week-1 posts get
--    re-touched in a later week.
-- 2. is_substantive column added -- 46 of 234 real rows excluded as
--    non-substantive (moderator/rules messages, bare weekly-thread
--    titles with zero added commentary, photo-credit-only posts,
--    bare name mentions, name collisions with other people). This is
--    a real, meaningful filter: Reddit's negative share among
--    substantive content is 61%, not 46% -- the excluded noise was
--    diluting the true skew, not amplifying it.
-- 3. Engagement-weighted breakdown added -- reveals a real,
--    non-obvious pattern: TikTok's raw sentiment mix looks fairly
--    even, but 70% of its actual engagement volume sits on NEUTRAL
--    content specifically, not positive or negative.
alter table earned_mentions add column if not exists is_substantive boolean default true;

-- (real backfilled non-substantive IDs applied directly via one-off
-- update during this session -- see conversation history for the full
-- reviewed list; not re-listed here since it's specific to the 234
-- rows scored at that time, not a repeatable migration step)

drop view if exists da_mindshare_sentiment_weekly;
create view da_mindshare_sentiment_weekly as
select
  date_trunc('week', fetched_at)::date as week_start,
  platform,
  count(*) as total_touched,
  count(*) filter (where created_at::date >= date_trunc('week', fetched_at)::date) as genuinely_new,
  count(*) filter (where is_substantive) as substantive_mentions,
  round(100.0 * count(*) filter (where is_substantive and sentiment = 'positive') / nullif(count(*) filter (where is_substantive), 0), 0) as pct_positive,
  round(100.0 * count(*) filter (where is_substantive and sentiment = 'negative') / nullif(count(*) filter (where is_substantive), 0), 0) as pct_negative,
  round(100.0 * count(*) filter (where is_substantive and sentiment = 'neutral') / nullif(count(*) filter (where is_substantive), 0), 0) as pct_neutral,
  round(100.0 * count(*) filter (where is_substantive and sentiment = 'mixed') / nullif(count(*) filter (where is_substantive), 0), 0) as pct_mixed,
  sum(like_count + comment_count + share_count) filter (where is_substantive) as total_engagement,
  sum(like_count + comment_count + share_count) filter (where is_substantive and sentiment = 'positive') as engagement_positive,
  sum(like_count + comment_count + share_count) filter (where is_substantive and sentiment = 'negative') as engagement_negative,
  sum(like_count + comment_count + share_count) filter (where is_substantive and sentiment = 'neutral') as engagement_neutral,
  sum(like_count + comment_count + share_count) filter (where is_substantive and sentiment = 'mixed') as engagement_mixed
from earned_mentions
where sentiment is not null
group by week_start, platform
order by week_start, platform;
