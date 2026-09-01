-- ============================================================
-- Migration 012: Podcast audience demographics + ad bookings
-- ============================================================
--
-- Prompted by the updated Podstock pull prompt now correctly capturing
-- Audience and Schedule sections (previously the existing parser/schema
-- only handled Overview + Channels). Two genuinely different shapes needed:

-- Mirrors social_audience_demographics' dimension/dimension_value pattern.
create table if not exists podcast_audience_demographics (
  id bigint generated always as identity primary key,
  show_id text not null,
  dimension text not null,        -- age | gender | country
  dimension_value text not null,
  value numeric(10,4) not null,   -- % of total delivery
  period_date date not null,
  created_at timestamptz not null default now(),
  unique (show_id, dimension, dimension_value, period_date)
);
alter table podcast_audience_demographics enable row level security;

-- NOTE: country percentages will not sum to exactly 100% -- the source
-- itself only lists countries down to a threshold; a genuine long tail
-- below that isn't individually broken out. Not a data error.

-- Genuinely different shape from podcast_metrics: deal/booking-level data
-- (who, what slot, booked or not), not a numeric time series. Real
-- visibility into confirmed future ad revenue.
create table if not exists podcast_ad_bookings (
  id bigint generated always as identity primary key,
  show_id text not null,
  episode_air_date date not null,
  episode_title text,
  brand text,  -- NULLABLE: an 'Available' (unbooked) slot has no brand
  slot_type text,
  status text not null,           -- 'Booked' | 'Available'
  notes text,                     -- e.g. 'HOLD', 'Requires Preapproval'
  pulled_at date not null,        -- which daily pull surfaced this booking
  created_at timestamptz not null default now(),
  unique (show_id, episode_air_date, slot_type, pulled_at)
);
alter table podcast_ad_bookings enable row level security;

-- First real data loaded 2026-08-27: 27 Overview/Channels metrics,
-- 26 audience demographic rows, 35 ad bookings (34 booked, 1 open slot).

-- Follow-up: closing gaps found by re-checking the 2026-08-27 pull line by
-- line against what was actually stored. Real gaps found and fixed:
--   1. pct_change column added -- was silently dropping every trend %
--      figure across the whole pull (24 values backfilled for 2026-08-27).
--   2. time_per_delivery_seconds added -- duration format ("21m 22s")
--      wasn't fitting the numeric-only value column; converted to seconds.
--   3. Episode platform-split rows added (episode_delivery_pct /
--      episode_delivery_count per platform) -- fit the existing schema,
--      were just omitted originally.
--   4. podcast_top_episode_snapshots table added for the named/dated
--      top-performer record, which doesn't fit a plain metric shape.
--
-- KNOWN LIMITATION, not fixed: the source pull showed "South Africa 0.2%"
-- twice (flagged explicitly by the user as "[appears twice, as
-- displayed]"). podcast_audience_demographics has a unique constraint on
-- dimension_value, so only one South Africa row can exist per day -- if
-- those were genuinely two distinct data points, one was discarded. Not
-- resolved since it's unclear what the second entry actually represented.

alter table podcast_metrics add column if not exists pct_change numeric(6,2);

create table if not exists podcast_top_episode_snapshots (
  id bigint generated always as identity primary key,
  show_id text not null,
  episode_title text not null,
  episode_air_date date,
  total_delivery numeric(12,0) not null,
  pulled_at date not null,
  created_at timestamptz not null default now(),
  unique (show_id, pulled_at)
);
alter table podcast_top_episode_snapshots enable row level security;

-- Follow-up: closing real gaps found by comparing the loaded data back
-- against the original pull line-by-line.
--
-- 1. pct_change added to podcast_metrics -- previously every %-change
--    figure across the entire pull was silently dropped (no column existed
--    for it), losing trend context on nearly every metric, every day.
alter table podcast_metrics add column if not exists pct_change numeric(8,4);

-- 2. "Time per delivery" (a duration like "21m 22s") was skipped entirely
--    since it doesn't fit a numeric-only column as text. Now converted to
--    total seconds (21m 22s = 1282) and stored as
--    metric='time_per_delivery_seconds'.
--
-- 3. Episodes' platform split (Spotify/Downloads/YouTube avg delivery per
--    episode, both % and count) was never captured -- confirmed these ARE
--    the breakdown of avg_delivery_per_episode (26063+22863+5918=54844,
--    exactly matching the already-stored total) -- added as
--    metric='avg_delivery_per_episode' / 'avg_delivery_per_episode_pct',
--    split by platform.
--
-- 4. New table for the named top-performing episode (title + air date +
--    delivery number) -- a genuinely different shape from a plain metric,
--    doesn't fit podcast_metrics.
create table if not exists podcast_top_episode (
  id bigint generated always as identity primary key,
  show_id text not null,
  episode_title text not null,
  episode_air_date date,
  total_delivery numeric(12,2) not null,
  period_date date not null,
  created_at timestamptz not null default now(),
  unique (show_id, period_date)
);
alter table podcast_top_episode enable row level security;

-- STILL a known, unresolved limitation: the source pull explicitly showed
-- "South Africa 0.2%" TWICE ("[appears twice, as displayed]"). The unique
-- constraint on (show_id, dimension, dimension_value, period_date) means
-- only one South Africa row can exist per day -- if those were genuinely
-- two distinct data points, one was silently discarded. Not fixed, since
-- it's unclear whether this reflects two real distinct figures or a
-- Podstock display glitch -- flagging rather than guessing at a fix.

-- Follow-up: corrected two silent metric-naming regressions introduced
-- during the parser rewrite (caught by testing against a REAL older
-- fixture, not synthetic data): "engagements_total" should have been
-- "total_interactions", and per-platform "followers" should have been
-- "subscribers" -- these are the names real historical data already used.
-- Retroactively renamed on the 2026-08-27 rows already written.
update podcast_metrics set metric = 'total_interactions'
where metric = 'engagements_total';

update podcast_metrics set metric = 'subscribers'
where metric = 'followers' and platform in ('Spotify', 'Apple', 'YouTube');
