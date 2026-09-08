-- ============================================================
-- Migration 021: Fixes from full-system regression (Sep 5, 2026)
-- ============================================================

-- FIX 1: Orphaned social_accounts row with blank account_id.
-- Root cause was in tiktok_connector.seed_account(), NOT the data:
-- TIKTOK_BUSINESS_ID is typically set to an empty string while TikTok
-- Accounts API approval is pending (the env var is still required), and
-- seed_account() wrote that blank value straight into social_accounts.
-- The row had been manually deleted at least twice in earlier sessions
-- and kept returning, because the deletions treated the symptom while
-- the connector recreated it every run. Connector now refuses to seed a
-- blank ID (3 regression tests added). This delete should finally stick.
delete from social_accounts where account_id is null or trim(account_id) = '';

-- FIX 2: Security advisor WARN -- mutable search_path on the trigger
-- function. An unqualified search_path is a real privilege-escalation
-- vector (a schema earlier in the path could shadow a referenced
-- object). Pinned, and re-verified adversarially afterwards: a
-- deliberate attempt to set a Non-Operating row's category to 'income'
-- is still correctly blocked.
create or replace function enforce_non_operating_category()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.source = 'Non-Operating' then
    new.category := 'non_operating';
  end if;
  return new;
end;
$$;

-- FIX 3: Security advisor ERROR -- da_mindshare_sentiment_weekly was
-- created with Postgres's default SECURITY DEFINER semantics, so it ran
-- with the creator's permissions and bypassed RLS for any caller.
alter view da_mindshare_sentiment_weekly set (security_invoker = true);
