#!/bin/bash
# update_repo.sh — Pulls today's complete set of changes into your local
# clone and pushes to GitHub. Run from inside your repo root
# (dani-austin-supabase), NOT from inside connectors/.
#
# What this does:
#   1. Extracts the latest full package over your local files
#   2. Shows you exactly what changed before committing anything
#   3. Commits with a full, accurate record of today's work
#   4. Pushes to GitHub
#
# Safe to run: git only stages real differences, so files that didn't
# change today are untouched even though the whole package gets extracted.

set -e  # stop on any real error, don't push a half-finished state

echo "=== Step 1: Extract the latest package over your local repo ==="
echo "Make sure dani-austin-supabase.zip has been downloaded to this"
echo "directory first (the same folder as this script)."
read -p "Press Enter once the zip is here, or Ctrl+C to stop..."

unzip -o dani-austin-supabase.zip -d /tmp/da-update-staging > /dev/null
# The zip contains a top-level da-supabase/ folder -- copy its contents
# into the repo root, not the zip's own folder structure.
cp -r /tmp/da-update-staging/da-supabase/* .
rm -rf /tmp/da-update-staging

echo ""
echo "=== Step 2: Review what actually changed ==="
git status
echo ""
read -p "Review the file list above. Press Enter to continue, or Ctrl+C to stop and review further..."

echo ""
echo "=== Step 3: Run tests one more time before committing ==="
cd connectors
python -m pytest tests/ || { echo "TESTS FAILED -- stopping before commit."; exit 1; }
cd ..

echo ""
echo "=== Step 4: Stage, commit, push ==="
git add .
git commit -m "$(cat <<'COMMITMSG'
Data quality fixes + Meta API demographics: category root cause, real-opex classification, income waterfall validation, Facebook demographics

QUICKBOOKS
- Root-cause fix: category was hardcoded by QB entity type, not real
  account classification. Expanded category check constraint to add
  'non_operating' as a real third state.
- Fixed category (not just source) for all 17 Non-Operating accounts,
  removing $44.6M of balance-sheet contamination from da_pnl.
- Income Tax moved Overhead -> Non-Operating.
- 163 real-opex/balance-sheet accounts classified from needs_review,
  each with a per-account note marked "not Katelyn-confirmed".
  needs_review dropped from ~8,270 rows to 1,906 (only Sales and
  Digital Product Revenue remain, both deliberately unclassified).
- 3 new revenue accounts classified to Partnerships (Anna Marie Austin,
  Olivia Swanson, Wig Revenue).
- Real cross-references caught: Wig Business Fees -> Partnerships,
  Podcast Travel/Revenue -> Podcast (not generic Overhead).

AIRTABLE
- Fixed table name (Master Tracking -> Partnerships, confirmed via
  live schema check) and all 9 field-name mappings against the real
  base schema.
- Fixed date parsing: Month Committed/Completed are free text, not
  real date fields. Added "Month YYYY" parsing (recovers ~83% of
  values), left bare month names and source-typos null rather than
  guessed.
- Fixed in_qbo checkbox semantics: Airtable omits unchecked boxes from
  API responses entirely; absence now correctly maps to false, not null.

META / SOCIAL
- Facebook post-stall (BUG-1): confirmed RESOLVED as a genuine content
  gap, not a bug -- live diagnostic + direct Page check confirmed no
  posts exist after June 3/4 either.
- Facebook demographics (BUG-2): built fetch_facebook_demographics()
  against a confirmed real request shape (period=day, not lifetime).
  Caught and fixed a real bug during testing: the function initially
  used the wrong access token (System User instead of Page token).
- TikTok "static followers": resolved as a display-rounding artifact,
  not a bug -- following/likes/uploads genuinely vary in the same
  payload. Added backfill_from_daily_history() to use Social Blade's
  already-returned 30-day history, previously discarded.
- Removed deprecated page_total_actions metric.
- Documented "followers" as the canonical FB follower field vs.
  page_follows (a separate, laggier Insights metric).
- Built social_account_identity canonical cross-platform account
  mapping table.

TESTS
- 109 tests passing (up from 93 at session start), including new
  regression guards for every fix above.

Full detail in Dani_Austin_Claude_Project_Instructions.md.
COMMITMSG
)"

git push

echo ""
echo "=== Done. Verify on GitHub that the push landed correctly. ==="
