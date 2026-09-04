-- ============================================================
-- Migration 018: Benchmark against both bug reports -- real regression found and fixed
-- ============================================================
--
-- Benchmarking today's fixes against the original DA_Data_Scrub_Report and
-- Meta_API_Bug_Report found a REAL regression: CRIT #1/#2's category fix
-- was applied retroactively (one-time SQL update) but the connector's
-- entity-type-based category derivation was never patched. Result: 15
-- A/R rows had already drifted back to category='income' by the daily
-- 90-day rolling sync, most recently Aug 31 -- five days after the
-- original fix.
--
-- Re-closed the immediate drift, then built a PERMANENT database-level
-- guard so this can't happen again regardless of connector code state:
create or replace function enforce_non_operating_category()
returns trigger as $$
begin
  if new.source = 'Non-Operating' then
    new.category := 'non_operating';
  end if;
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_enforce_non_operating_category on qb_da_transaction_lines;
create trigger trg_enforce_non_operating_category
before insert or update on qb_da_transaction_lines
for each row execute function enforce_non_operating_category();

-- Verified directly: deliberately tried to set category='income' on an
-- A/R row with source='Non-Operating' -- trigger correctly blocked it.
--
-- Also cleaned up: 15 stale page_total_actions rows that were never
-- deleted after the metric was removed from the connector's request list
-- (code stopped requesting new data, but old zero rows were never purged).
--
-- Confirmed still correct, no action needed: needs_review split (CRIT #3),
-- social_account_identity (MED #7), Facebook post stall correctly still
-- frozen at June 3 (BUG-1/HIGH #6, a real content gap not a bug),
-- affiliate_revenue correctly still empty and documented (MED #8).
--
-- Confirmed CODE-COMPLETE BUT NOT YET DATA-COMPLETE (needs a real live
-- run from Shahzad, not something fixable from Supabase directly):
-- fetch_facebook_demographics() (BUG-2) -- 0 real rows landed yet.
-- backfill_from_daily_history() (HIGH #5 / TikTok) -- only 1 distinct
-- value stored, meaning the backfill was built/tested but never actually
-- run against live Social Blade data.
