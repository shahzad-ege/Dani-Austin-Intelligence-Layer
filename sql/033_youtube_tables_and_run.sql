-- ============================================================
-- Migration 033: YouTube tables + missing run() function (Sep 23 2026)
-- ============================================================
-- REAL, SIGNIFICANT FINDING: youtube_connector.py had every individual
-- function built and hardened (fetch_video_stats, fetch_video_analytics,
-- _get_oauth_access_token), but was NEVER wired into a runnable entry
-- point -- no run() function, no `if __name__ == "__main__":` block
-- anywhere. Running `python youtube_connector.py` directly defined a
-- set of functions and exited silently with zero output. Confirmed
-- this had genuinely never run end-to-end: neither target table
-- existed in Supabase at all before this migration.
create table if not exists youtube_video_stats (
  id bigint generated always as identity primary key,
  video_id text not null unique,
  title text,
  published_at date,
  view_count integer default 0,
  like_count integer default 0,
  comment_count integer default 0,
  business_unit text default 'Podcast',
  updated_at timestamptz default now()
);

create table if not exists youtube_video_analytics (
  id bigint generated always as identity primary key,
  video_id text not null,
  period_date date not null,
  average_view_duration_seconds numeric,
  average_view_percentage numeric,
  subscribers_gained integer default 0,
  business_unit text default 'Podcast',
  updated_at timestamptz default now(),
  unique(video_id, period_date)
);

create policy "internal_tools_select" on youtube_video_stats for select to anon, authenticated using (true);
create policy "internal_tools_update" on youtube_video_stats for update to anon, authenticated using (true) with check (true);
create policy "internal_tools_insert" on youtube_video_stats for insert to anon, authenticated with check (true);

create policy "internal_tools_select" on youtube_video_analytics for select to anon, authenticated using (true);
create policy "internal_tools_update" on youtube_video_analytics for update to anon, authenticated using (true) with check (true);
create policy "internal_tools_insert" on youtube_video_analytics for insert to anon, authenticated with check (true);

-- run() added to youtube_connector.py: pulls public video stats first
-- (gives the real video_id list), then pulls private Analytics data
-- for those same videos over the last 7 days -- a real, recent window,
-- not a full historical pull on every run. A revoked/expired OAuth
-- token during the Analytics step does not wipe out stats already
-- successfully written moments earlier.
