"""
diagnose_credit_memo.py — Confirms the real, live structure of
QuickBooks CreditMemo records before building any extraction logic.

WHY THIS EXISTS: a broad entity-type sweep found real CreditMemo data
($28,500 in just a 5-record sample from 2023 onward) that this
connector has never captured. CreditMemo represents credits issued to
customers -- if not captured, current revenue totals may be
overstated, the same class of real finding as payroll and LTK before
it (real, material data hiding in an unqueried entity type), though
here the risk is overstatement rather than complete absence.

This does NOT assume CreditMemo's real structure -- same
diagnostic-first discipline as every other new entity type in this
project. Pulls a real sample and prints the complete raw shape.
"""

import os
import json
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

QB_CLIENT_ID = os.environ["QB_CLIENT_ID"]
QB_CLIENT_SECRET = os.environ["QB_CLIENT_SECRET"]
QB_REALM_ID = os.environ["QB_REALM_ID"]
QB_ENVIRONMENT = (os.environ.get("QB_ENVIRONMENT") or "production").strip().lower()

QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_API_BASE = (
    "https://quickbooks.api.intuit.com"
    if QB_ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)


def get_access_token() -> str:
    from db import get_client

    client = get_client()
    result = client.table("qb_oauth_credentials").select("*").eq("realm_id", QB_REALM_ID).execute()
    if not result.data:
        raise RuntimeError("No stored refresh token found -- run the regular sync at least once first.")
    current_refresh_token = result.data[0]["refresh_token"]

    resp = requests.post(
        QB_TOKEN_URL,
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        data={"grant_type": "refresh_token", "refresh_token": current_refresh_token},
        headers={"Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED to refresh token ({resp.status_code}): {resp.text}")
        raise RuntimeError("Token refresh failed.")

    token_data = resp.json()
    from writer import upsert_rows
    upsert_rows("qb_oauth_credentials", [{"realm_id": QB_REALM_ID, "refresh_token": token_data["refresh_token"]}])
    return token_data["access_token"]


def main() -> None:
    print(f"Environment: {QB_ENVIRONMENT}")
    print("Refreshing access token...")
    access_token = get_access_token()
    print("Token refreshed.\n")

    # Full 2018-onward range this time, not just the 2023+ existence
    # check -- want the real total scope, not just confirmation it exists.
    query = "SELECT * FROM CreditMemo WHERE TxnDate >= '2018-01-01' MAXRESULTS 1000"
    print(f"Querying: {query}\n")

    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )

    if resp.status_code >= 400:
        print(f"Status: {resp.status_code}")
        print(f"FAILED: {resp.text}")
        return

    data = resp.json()
    records = data.get("QueryResponse", {}).get("CreditMemo", [])
    print(f"Status: {resp.status_code} -- {len(records)} real CreditMemo record(s) found (2018 onward).\n")

    if not records:
        print("Zero records in the full range -- the earlier sample may have been an edge case.")
        return

    total = sum(float(r.get("TotalAmt", 0) or 0) for r in records)
    print(f"Real total across all {len(records)} records: ${total:,.2f}\n")

    print("Full raw shape of the FIRST record (this defines what fields")
    print("the real extraction logic should use):")
    print(json.dumps(records[0], indent=2))

    # Real, useful breakdown: which real accounts/items do these credits
    # actually hit? This determines whether they're concentrated in one
    # business unit (like LTK was) or spread across several.
    print("\n--- Real accounts referenced across all records ---")
    accounts_seen = {}
    for r in records:
        for line in r.get("Line", []):
            detail = line.get("SalesItemLineDetail") or {}
            item_name = (detail.get("ItemRef") or {}).get("name", "(no item)")
            accounts_seen[item_name] = accounts_seen.get(item_name, 0) + float(line.get("Amount", 0) or 0)
    for name, amt in sorted(accounts_seen.items(), key=lambda x: -x[1]):
        print(f"  {name}: ${amt:,.2f}")

    print("\n--- Next step ---")
    print("Paste this full output back. The real extraction logic will be")
    print("built to match these confirmed real field names, not guessed at.")


if __name__ == "__main__":
    main()
