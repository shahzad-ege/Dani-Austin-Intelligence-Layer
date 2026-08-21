# Dani Austin — Supabase Intelligence Layer

Data pipeline for Dani Austin LLC's business intelligence spoke, isolated
from the EGE family-office hub. Pulls QuickBooks, Airtable, Social Blade,
Meta, TikTok, and manual exports into a scoped Supabase project; Jordan
queries it in plain English via a Claude project with source-of-truth
routing rules.

Architecture reference: source-of-truth routing — booked revenue →
QuickBooks, pipeline → Airtable, forecasts → the projections tables, audience
→ social APIs. Never sum revenue across sources.

## Repo structure

```
.
├── connectors/
│   ├── db.py                          # Supabase client (service-role key)
│   ├── models.py                      # Record schemas, one per table
│   ├── writer.py                      # Idempotent upsert logic
│   ├── qb_connector.py                # QuickBooks Online
│   ├── airtable_connector.py          # Airtable Partnerships base
│   ├── social_blade_connector.py      # Social Blade (no approval needed)
│   ├── meta_connector.py              # Instagram + Facebook (Graph API v25.0)
│   ├── tiktok_connector.py            # TikTok Accounts API (organic metrics)
│   ├── brex_connector.py              # Brex cash balances -> da_cash_current_balance
│   ├── paypal_connector.py            # PayPal, both DA accounts -> da_cash_current_balance
│   ├── plaid_connector.py             # Chase Business, filtered from shared EGE token
│   ├── manual_forecast_connector.py   # Revenue Projections + Cash Forecast CSVs
│   ├── manual_affiliate_connector.py  # Amazon + LTK affiliate CSVs
│   ├── manual_podcast_connector.py    # Podstock CSV placeholder (legacy path)
│   ├── podstock_parse_pull.py         # Parses Claude-in-Chrome's Podstock text pull -> podcast_metrics
│   ├── data/                          # Drop manual CSV exports here
│   ├── run_all.py                     # Runs every connector, isolates failures
│   └── requirements.txt
├── sql/
│   └── 001_initial_schema.sql   # Full schema + RLS, mirrors what's live
└── .github/workflows/
    ├── daily-sync.yml           # Runs run_all.py on a schedule
    └── apply-migrations.yml     # Manual: applies sql/*.sql to the DB
```

## Setup

1. **Add GitHub Secrets** (Settings → Secrets and variables → Actions):
   - `DA_SUPABASE_URL`, `DA_SUPABASE_SERVICE_KEY`
   - `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_REFRESH_TOKEN`, `QB_REALM_ID`
   - `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`
   - `SOCIALBLADE_CLIENT_ID`, `SOCIALBLADE_TOKEN`
   - `BREX_API_TOKEN`
   - `PAYPAL_CLIENT_ID_DANI`, `PAYPAL_CLIENT_SECRET_DANI`
   - `PAYPAL_CLIENT_ID_KATELYN`, `PAYPAL_CLIENT_SECRET_KATELYN`
   - `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ACCESS_TOKEN`, `PLAID_DA_ACCOUNT_ID`
   - `META_SYSTEM_USER_TOKEN`, `META_IG_USER_ID`, `META_PAGE_ID`
   - `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`, `TIKTOK_BUSINESS_ID`
   - `DA_DATABASE_URL` (only needed if you use `apply-migrations.yml`)

   Connectors missing their secrets won't crash the whole job — `run_all.py`
   isolates each connector and logs a failure for that one only.

2. **For the manual connectors** (revenue forecast, cash forecast, affiliate,
   podcast), drop the corresponding CSV into `connectors/data/` before a run.
   If the file isn't there yet, that connector logs a skip message and moves
   on — it won't fail the job. See each `manual_*_connector.py` docstring for
   the expected CSV shape (all inferred from the reporting spec, not yet
   confirmed against real exports).

3. **Schema is already live** in the "Dani Austin" Supabase project,
   including `affiliate_commission_deals` (direct-brand commission deals
   like Stanley — distinct from platform/marketplace affiliate revenue) and
   the `rls_auto_enable()` public-execute fix. `sql/001_initial_schema.sql`
   and `sql/002_lock_down_rls_auto_enable.sql` are there for reproducibility
   (e.g. spinning up a staging project) — you don't need to re-run them
   against the current one.

4. **Daily sync runs automatically** once secrets are set — see
   `.github/workflows/daily-sync.yml`. Trigger manually anytime via the
   Actions tab → "Daily Data Sync" → "Run workflow."

## Testing

`connectors/tests/` has an offline test suite — every connector's parsing
logic is tested against fake API responses, with `requests` and
`upsert_rows` mocked out. No real credentials or network calls needed:

```bash
cd connectors
pip install -r requirements.txt
DA_SUPABASE_URL=fake DA_SUPABASE_SERVICE_KEY=fake python -m pytest tests/ -v
```

Runs automatically on every push via `.github/workflows/run-tests.yml`.

**What this catches:** bugs in our own parsing/transform logic (wrong field
name, bad date handling, incorrect aggregation math).
**What this doesn't catch:** whether the real QuickBooks/Airtable/Meta/
TikTok APIs actually return the shape the code assumes — that's still only
verifiable once real credentials exist. Treat passing tests as "our code is
internally correct," not "this connector is production-ready."

The schema itself (views, joins, constraints) has been separately
smoke-tested with dummy rows inserted directly and cleaned up — see the
project plan for what that surfaced (notably: `qb_da_transaction_lines` has
no dedicated `invoice_no` column yet; the QuickBooks↔Airtable reconciliation
currently falls back to matching QuickBooks' `doc_num` inside `memo`, which
needs confirming against real data before trusting it).

## Status — what's live vs. pending

| Connector | Status |
|---|---|
| QuickBooks | **Live with real data**: 631 transaction lines. Rewritten from a Reports API to an Accounting API entity-query approach after the Reports API version proved to lose 82.7% of real transactions in production (identifier bug — `doc_num` is optional and blank on most transaction types; QuickBooks' real `Id` field is used now). Category (income/expense) is deterministic from entity type. Refresh-token rotation persisted automatically. **`source`/business-unit**: confirmed via direct diagnostic that this QuickBooks company doesn't use Class tracking at all — replaced with an account-name lookup table (`qb_account_business_unit_map`), same pattern as the Domas reference connector. Unmapped accounts explicitly return `needs_review`, never guessed. 14 tests. |
| Airtable | Code written, untested. `FIELD_MAP` in `airtable_connector.py` is a best guess — confirm field names against the real base. |
| Social Blade | Code written, untested. No approval needed — just needs a clientid/token from the Social Blade Developer Console. Confirm endpoint paths and `FIELD_MAP` against a live response before first run. |
| Meta (IG/FB) | Code written, untested — waiting on App Review (~20-day typical window) and a System User token. Pinned to Graph API v25.0. Watch for Meta's announced `reach`→`page_viewer` shift on Page insights, expected end of June 2026 — not yet handled, `reach` is still requested as a bridge metric. |
| TikTok | Code written, untested — waiting on TikTok Accounts API access. Uses the Accounts API (not Display/Research API), which requires the new Accounts API Access Application Form submitted before March 20, 2026. |
| Manual: revenue forecast + cash flow | Code written. Reads CSV from `connectors/data/`; format is inferred, needs confirming against Katelyn's real exports. |
| Manual: affiliate (Amazon + LTK) | Code written. Amazon's PA-API does NOT expose commission data — real commission access requires requesting S3 Activity Report credentials from Amazon Associates support, or dashboard CSV export in the meantime. LTK has no public API; dashboard export is the supported path. |
| Manual: podcast (Podstock) | **Confirmed: no public API exists.** Deep research (Podstock's own privacy policy, ToS, marketing site) plus direct confirmation of no API access in the account itself. Working path instead: a scheduled Claude-in-Chrome browser task (prompt: `podstock_daily_pull_prompt.md`) runs daily on Jordan's machine, extracts dashboard data, and `podstock_parse_pull.py` converts that output into `podcast_metrics` rows. Tested against real captured data (18/18 metrics parsed correctly). Deliberately out of scope: Episodes, Schedule (ad bookings), and Audience (demographics) sections don't fit `podcast_metrics`' shape and are explicitly flagged as skipped rather than force-fit or silently dropped -- would need their own tables if wanted. |
| Plaid (Chase) | Code written, tested (4 tests, including a critical test proving the other 4 EGE-family accounts are correctly discarded). The access token is shared across the whole EGE family office and returns 5 accounts total — this connector filters to only Dani Austin's via an explicit account_id allowlist, never a name-based guess. |
| Brex | Code written, untested. Feeds the same `da_cash_current_balance` table as Plaid. App registered, waiting on the actual API token (Brex Dashboard → Developer → Settings → Create Token). Structured to support a second Brex account later, but only one is currently confirmed to exist for Dani Austin. |
| PayPal | Code written, untested. Both Dani Austin accounts (including Katelyn's, which she manages on Dani's behalf) written as separate rows in `da_cash_current_balance` — not combined into one figure, so account-level detail is preserved. Credentials confirmed in hand. |
| `da_entity_summary` sync to EGE hub | Table exists, sync logic not built. |
| DA Claude project + routing prompt | Not built. |

See the project plan doc for full phase sequencing and open questions.
