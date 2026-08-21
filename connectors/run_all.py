"""
run_all.py — Scheduled entry point for all Dani Austin connectors.

Run daily via GitHub Actions (same schedule pattern as the EGE build).
Each connector is isolated: one failing (e.g. Airtable rate-limited) doesn't
block the others from running and doesn't crash the whole job.

Currently wired: QuickBooks, Airtable, Social Blade, Meta, TikTok, Brex,
PayPal (both DA accounts), Plaid/Chase (filtered from a shared multi-entity
token), and the manual CSV-ingestion connectors (forecast, affiliate,
podcast placeholder).

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
import traceback

import qb_connector
import airtable_connector
import social_blade_connector
import meta_connector
import tiktok_connector
import brex_connector
import paypal_connector
import plaid_connector
import manual_forecast_connector
import manual_affiliate_connector
import manual_podcast_connector

CONNECTORS = [
    ("quickbooks", qb_connector.run),
    ("airtable", airtable_connector.run),
    ("social_blade", social_blade_connector.run),
    ("meta", meta_connector.run),
    ("tiktok", tiktok_connector.run),
    ("brex", brex_connector.run),
    ("paypal", paypal_connector.run),
    ("plaid", plaid_connector.run),
    ("manual_forecast", manual_forecast_connector.run),
    ("manual_affiliate", manual_affiliate_connector.run),
    ("manual_podcast", manual_podcast_connector.run),
]


def main() -> int:
    exit_code = 0
    for name, run_fn in CONNECTORS:
        try:
            count = run_fn()
            print(f"[{name}] OK — {count} rows upserted")
        except Exception:
            exit_code = 1
            print(f"[{name}] FAILED")
            traceback.print_exc()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
