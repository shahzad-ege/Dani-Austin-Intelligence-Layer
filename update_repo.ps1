# update_repo.ps1 — PowerShell version, for your actual environment.
# Run from your repo root (dani-austin-supabase), NOT from inside
# connectors\. Requires dani-austin-supabase.zip already downloaded to
# this same folder.

$ErrorActionPreference = "Stop"

Write-Host "=== Step 1: Extract the latest package over your local repo ===" -ForegroundColor Cyan
if (-not (Test-Path ".\dani-austin-supabase.zip")) {
    Write-Host "dani-austin-supabase.zip not found in this folder. Download it first." -ForegroundColor Red
    exit 1
}

$staging = "$env:TEMP\da-update-staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
Expand-Archive -Path ".\dani-austin-supabase.zip" -DestinationPath $staging

# The zip contains a top-level da-supabase\ folder -- copy its CONTENTS
# into the repo root, not the folder itself.
Copy-Item -Path "$staging\da-supabase\*" -Destination "." -Recurse -Force
Remove-Item $staging -Recurse -Force

Write-Host ""
Write-Host "=== Step 2: Review what actually changed ===" -ForegroundColor Cyan
git status
Write-Host ""
Read-Host "Review the file list above. Press Enter to continue, or Ctrl+C to stop"

Write-Host ""
Write-Host "=== Step 3: Run tests one more time before committing ===" -ForegroundColor Cyan
Push-Location connectors
python -m pytest tests/
if ($LASTEXITCODE -ne 0) {
    Write-Host "TESTS FAILED -- stopping before commit." -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

Write-Host ""
Write-Host "=== Step 4: Stage, commit, push ===" -ForegroundColor Cyan
git add .

$commitMessage = @"
Data quality fixes + Meta API demographics: category root cause, real-opex classification, income waterfall validation, Facebook demographics

QUICKBOOKS
- Root-cause fix: category was hardcoded by QB entity type, not real
  account classification. Expanded category check constraint to add
  'non_operating' as a real third state.
- Fixed category (not just source) for all 17 Non-Operating accounts,
  removing `$44.6M of balance-sheet contamination from da_pnl.
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
"@

git commit -m $commitMessage
git push

Write-Host ""
Write-Host "=== Done. Verify on GitHub that the push landed correctly. ===" -ForegroundColor Green
