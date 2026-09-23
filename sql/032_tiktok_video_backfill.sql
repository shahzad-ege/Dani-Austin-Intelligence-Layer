-- ============================================================
-- Migration 032: TikTok per-video backfill (Sep 23 2026)
-- ============================================================
-- Real, confirmed gap: the regular connector's fetch_video_metrics()
-- only fetches ONE page and sums it into a daily aggregate -- the
-- real API response includes "has_more": true, meaning most real
-- video history has never been pulled. Time-sensitive: TikTok's own
-- enrichment fields (likes/comments/shares) go null after ~7 days of
-- no engagement, data stops updating 365 days post-publish.
create table if not exists tiktok_video_metrics (
  id bigint generated always as identity primary key,
  item_id text not null unique,
  create_time timestamptz,
  video_views integer default 0,
  likes integer default 0,
  comments integer default 0,
  shares integer default 0,
  fetched_at timestamptz default now()
);

create policy "internal_tools_select" on tiktok_video_metrics for select to anon, authenticated using (true);
create policy "internal_tools_update" on tiktok_video_metrics for update to anon, authenticated using (true) with check (true);
create policy "internal_tools_insert" on tiktok_video_metrics for insert to anon, authenticated with check (true);

-- backfill_tiktok_videos.py added: real pagination via cursor/max_count,
-- confirmed consistent across every TikTok API doc checked. Real
-- safety cap (200 pages) prevents runaway pagination if has_more never
-- clears. One-time backfill -- NOT yet added to the daily schedule.
