"""
diagnose_phyllo.py — Discovers the real Phyllo Social Listening API
response shape before building the full connector.

WHY THIS PIVOT HAPPENED: Brand24 and Awario both confirmed to require
Enterprise/custom pricing (~$1,500/mo) for API access -- rejected as
unacceptable. Octolens is genuinely affordable ($159-199/mo, API on all
plans) but its real platform coverage (Reddit, GitHub, Hacker News,
Stack Overflow, DEV.to) is built for B2B SaaS/developer-community
monitoring -- a poor fit for tracking mentions of a consumer lifestyle
influencer. Phyllo covers the actually-relevant platforms (Instagram,
TikTok, YouTube, X, LinkedIn) with a real, confirmed mid-market tier
($200-600/mo) -- the right coverage fit within budget.

WHY DIAGNOSTIC-FIRST: Phyllo's exact field-level API response shape for
the Social Listening endpoints specifically isn't published without a
real account (their public docs describe capability, not exact JSON
schemas at the free-research level this project can access). Same
lesson already learned twice this project (Facebook demographics,
TikTok rounding) -- confirm the real shape before writing a parser
against a guess.

SETUP NEEDED BEFORE RUNNING:
  1. Sign up at getphyllo.com -- a sandbox/dev tier exists for initial
     testing before committing to the paid mid-market tier.
  2. Obtain API credentials from the Phyllo dashboard (typically a
     Client ID + Client Secret, confirm exact names once in the
     dashboard -- Phyllo's docs reference OAuth-style credentials but
     the precise header/param names need confirming live).
  3. Set as environment variables:
       PHYLLO_CLIENT_ID
       PHYLLO_CLIENT_SECRET
       PHYLLO_API_BASE  (sandbox vs. production base URL differs --
                          confirm the correct one in the dashboard
                          before setting this)

Run with: python diagnose_phyllo.py
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

PHYLLO_CLIENT_ID = os.environ["PHYLLO_CLIENT_ID"]
PHYLLO_CLIENT_SECRET = os.environ["PHYLLO_CLIENT_SECRET"]
PHYLLO_API_BASE = os.environ.get("PHYLLO_API_BASE", "https://api.sandbox.getphyllo.com")


def main() -> None:
    print(f"Using base URL: {PHYLLO_API_BASE}")
    print("(Confirm this is the correct sandbox/production URL from your")
    print("Phyllo dashboard before trusting results from this run.)\n")

    # Phyllo's own docs describe Basic Auth (Client ID as username,
    # Client Secret as password) for most endpoints -- confirming this
    # is actually correct is exactly what this diagnostic is for, not
    # assumed.
    auth = (PHYLLO_CLIENT_ID, PHYLLO_CLIENT_SECRET)

    print("=== Testing basic connectivity: listing available accounts ===")
    resp = requests.get(f"{PHYLLO_API_BASE}/v1/accounts", auth=auth)
    print(f"Status: {resp.status_code}")

    if resp.status_code >= 400:
        print(f"FAILED. Response body: {resp.text}")
        print("\nIf 401: check Client ID/Secret are correct and the auth")
        print("method actually is Basic Auth (not a bearer token flow --")
        print("this needs confirming, not assuming).")
        print("If 404: check PHYLLO_API_BASE matches what's shown in your")
        print("actual Phyllo dashboard.")
        return

    data = resp.json()
    print("Full raw response:")
    print(json.dumps(data, indent=2)[:3000])

    print("\n--- Next step ---")
    print("If this succeeded, the real next call is whatever Phyllo's")
    print("dashboard shows as the Social Listening / mentions endpoint")
    print("specifically (distinct from their creator-profile-data")
    print("endpoints, which are a different product). Paste this output")
    print("back, along with the exact mentions-endpoint path from your")
    print("dashboard, and the real fetch_phyllo_mentions() function will")
    print("be built against the confirmed real shape.")


if __name__ == "__main__":
    main()
