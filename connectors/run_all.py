"""
run_all.py — Scheduled entry point for all Dani Austin connectors.

Run daily via GitHub Actions (same schedule pattern as the EGE build).
Each connector is isolated: one failing (e.g. Airtable rate-limited) doesn't
block the others from running and doesn't crash the whole job.

Currently wired: QuickBooks, Airtable, Social Blade, Meta, TikTok, Brex,
PayPal (both DA accounts), Plaid/Chase (filtered from a shared multi-entity
token), Megaphone episode metadata, and the manual CSV-ingestion
connectors (forecast, affiliate, podcast placeholder). Xpoz earned-mentions
tracking runs on its own separate weekly schedule
(.github/workflows/xpoz-weekly-sync.yml), NOT here -- see the note below.

Still needs real credentials/access before it does anything useful:
    - Meta            -- needs META_SYSTEM_USER_TOKEN etc.; App Review pending
    - TikTok           -- needs TikTok Accounts API credentials; access pending
    - Manual CSVs      -- will just skip and log if the expected file isn't
                          present yet (see each manual_*_connector.py docstring)

Not yet wired at all:
    - Podstock via API -- no public API exists; using manual CSV placeholder
                          until Dear Media confirms an access model
"""

import sys
import importlib
import traceback

# xpoz_connector deliberately NOT registered here -- it runs on its own
# weekly schedule (.github/workflows/xpoz-weekly-sync.yml), same pattern
# as post-level-sync.yml's separate 12-hourly cadence. Including it here
# would run it daily, exceeding the ~20% monthly budget target it was
# specifically sized for at weekly frequency.
#
# REAL FIX (Sep 23 2026 audit): connectors are now imported LAZILY,
# inside each one's own try/except, not at the top of this file. Six
# connectors read required env vars at module level (os.environ["X"]),
# so a single missing secret used to raise KeyError during import --
# killing the ENTIRE daily sync before any connector ran. Confirmed by
# simulating the real daily-sync.yml environment: megaphone_connector
# was registered here, but daily-sync.yml never passes MEGAPHONE_*
# secrets, so the next push would have broken every connector at once.
# Now a missing secret fails only its own connector.
CONNECTORS = [
    ("quickbooks", "qb_connector:run"),
    ("quickbooks_ar_aging", "qb_connector:sync_ar_aging"),
    ("airtable", "airtable_connector:run"),
    ("social_blade", "social_blade_connector:run"),
    ("meta", "meta_connector:run"),
    ("tiktok", "tiktok_connector:run"),
    ("brex", "brex_connector:run"),
    ("paypal", "paypal_connector:run"),
    ("plaid", "plaid_connector:run"),
    ("manual_forecast", "manual_forecast_connector:run"),
    ("manual_affiliate", "manual_affiliate_connector:run"),
    ("manual_podcast", "manual_podcast_connector:run"),
    ("megaphone", "megaphone_connector:run"),
]


def _resolve(target: str):
    module_name, fn_name = target.split(":")
    return getattr(importlib.import_module(module_name), fn_name)


def main() -> int:
    exit_code = 0
    for name, target in CONNECTORS:
        try:
            run_fn = _resolve(target)  # import happens HERE, isolated per connector
            count = run_fn()
            print(f"[{name}] OK — {count} rows upserted")
        except Exception:
            exit_code = 1
            print(f"[{name}] FAILED")
            traceback.print_exc()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
