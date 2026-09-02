-- ============================================================
-- Migration 017: DA_Data_Scrub_Report fixes (non-judgment items)
-- ============================================================
--
-- Independent data-quality audit (Sep 1 2026) found a real, deeper gap
-- beyond the earlier Non-Operating fix: qb_da_transaction_lines.category
-- was hardcoded by QuickBooks entity type, never by real account
-- classification -- meaning da_pnl (which sums raw category directly)
-- remained fully contaminated even after source/business-unit was fixed.

-- Expanded category check constraint to support the real third state.
alter table qb_da_transaction_lines drop constraint qb_da_transaction_lines_category_check;
alter table qb_da_transaction_lines add constraint qb_da_transaction_lines_category_check
  check (category = any (array['income'::text, 'expense'::text, 'non_operating'::text]));

-- Fixed category (not just source) for all Non-Operating accounts --
-- both the original 7 and 9 more surfaced by this audit. Removed $44.6M
-- of contamination from da_pnl in a single pass. Income Tax deliberately
-- excluded -- pending decision, not yet resolved.

-- Canonical cross-source account identity mapping (MED #7).
create table if not exists social_account_identity (
  id bigint generated always as identity primary key,
  platform text not null,
  api_account_id text,
  social_blade_account_id text,
  handle text not null,
  notes text,
  unique (platform)
);
alter table social_account_identity enable row level security;

-- Also cleaned: a second orphaned empty-account_id TikTok row in
-- social_accounts (same bug class fixed once before), confirmed zero
-- dependent rows before deleting.

-- Code fixes (meta_connector.py): removed deprecated page_total_actions
-- (confirmed all-zero, not dormant); documented "followers" as the
-- canonical FB follower field vs. page_follows (separate Insights metric
-- with its own lag, not interchangeable).

-- New diagnostic scripts (not data changes): diagnose_tiktok_social_blade.py,
-- diagnose_facebook_post_stall.py -- built to distinguish real pipeline
-- bugs from upstream data-freshness limitations, rather than guessing.

-- Follow-up: Income Tax moved to Non-Operating (direct decision), and the
-- full real-opex needs_review backlog classified in one pass -- 162
-- accounts, ~$700K previously excluded from Overhead. needs_review
-- dropped from ~8,270 rows to 1,906 (only Sales and Digital Product
-- Revenue remain, both deliberately still flagged). Every classification
-- marked "not Katelyn-confirmed" in qb_account_business_unit_map.notes
-- for later review. Real cross-references caught (Wig Business Fees ->
-- Partnerships, Podcast Travel/Revenue -> Podcast) rather than defaulting
-- everything to Overhead. Genuine low-confidence flags and one real,
-- unreconciled discrepancy (Related Business Expenses: $1,882 in QB vs.
-- $737,635 in the real P&L sheet) documented in the Claude Project
-- instructions rather than guessed past.
