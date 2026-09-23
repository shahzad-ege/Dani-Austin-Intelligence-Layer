-- ============================================================
-- Migration 034: YouTube expanded metrics + traffic sources (Sep 23 2026)
-- ============================================================
-- Real, confirmed via Google's own Analytics API documentation --
-- video-report metrics expanded from 3 (averageViewDuration,
-- averageViewPercentage, subscribersGained) to 9: adds views,
-- estimatedMinutesWatched, likes, comments, shares, subscribersLost.
alter table youtube_video_analytics
  add column if not exists views integer default 0,
  add column if not exists estimated_minutes_watched numeric default 0,
  add column if not exists likes integer default 0,
  add column if not exists comments integer default 0,
  add column if not exists shares integer default 0,
  add column if not exists subscribers_lost integer default 0;

-- New: real traffic source breakdown per video, confirmed real
-- dimension (insightTrafficSourceType) from Google's own Analytics
-- API sample requests -- this is the actual original motivation for
-- building OAuth in the first place, per this connector's own module
-- docstring ("retention curves, traffic sources").
create table if not exists youtube_traffic_sources (
  id bigint generated always as identity primary key,
  video_id text not null,
  period_date date not null,
  traffic_source_type text not null,
  views integer default 0,
  estimated_minutes_watched numeric,
  business_unit text default 'Podcast',
  updated_at timestamptz default now(),
  unique(video_id, period_date, traffic_source_type)
);

create policy "internal_tools_select" on youtube_traffic_sources for select to anon, authenticated using (true);
create policy "internal_tools_update" on youtube_traffic_sources for update to anon, authenticated using (true) with check (true);
create policy "internal_tools_insert" on youtube_traffic_sources for insert to anon, authenticated with check (true);

-- backfill_youtube.py added: fetches ALL real videos (no 50-video
-- cap), and Analytics/traffic-source data over each video's own real
-- lifetime (publish date -> today), not the regular connector's 7-day
-- rolling window. A revoked/expired token mid-backfill preserves
-- whatever was already successfully written rather than losing it.
