-- ============================================================
-- Migration 025: Megaphone episode metadata (Sep 2026)
-- ============================================================
-- Confirmed working via a real live API call, after resolving a real
-- 403 "does not have access to object requested" error -- the initial
-- API token belonged to an account without access to this specific
-- network; resolved using a token from an account that actually
-- administers it.
--
-- REAL, IMPORTANT LIMITATION: every field name in the real response was
-- inspected directly. There are NO download/play/listen counts
-- anywhere in this endpoint. The original motivation for this
-- connector ("Megaphone would be the authoritative source for true
-- per-episode downloads") is NOT satisfied by this endpoint alone --
-- real per-episode performance numbers likely require a separate
-- Megaphone analytics endpoint, not yet discovered.
--
-- What IS genuinely captured: real episode metadata (title, pubdate,
-- duration, episode/season number, publish status across RSS/Spotify)
-- and real structured ad-cuepoint data (ad count per episode) --
-- distinct, real data Podstock's browser-scrape doesn't provide.
create table if not exists podcast_episodes_megaphone (
  id bigint generated always as identity primary key,
  episode_id text not null unique,
  title text,
  pubdate date,
  duration_seconds numeric,
  episode_number integer,
  season_number integer,
  status text,
  spotify_status text,
  rss_status text,
  ad_count integer default 0,
  fetched_at timestamptz default now()
);

create policy "internal_tools_select" on podcast_episodes_megaphone for select to anon, authenticated using (true);
create policy "internal_tools_update" on podcast_episodes_megaphone for update to anon, authenticated using (true) with check (true);
create policy "internal_tools_insert" on podcast_episodes_megaphone for insert to anon, authenticated with check (true);
