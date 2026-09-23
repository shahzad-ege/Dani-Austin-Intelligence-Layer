"""
diagnose_amazon_gap.py — Checks two real hypotheses for the confirmed
$1,500/month Amazon shortfall (Jan-Jun 2026, resolved by July).

WHY THIS EXISTS: this project has now found three real, material gaps
(payroll, LTK, CreditMemo) all hiding in entity types this connector
never queried. The Amazon gap has been open and unexplained since
early in this project -- this applies the same live-diagnostic
discipline to it, rather than leaving it as a guess.

Checks two real hypotheses:
  1. A JournalEntry-based true-up/adjustment for Amazon, the same
     mechanism that explained LTK's returns adjustment -- our own
     synced data can't rule this out, since JournalEntry extraction is
     scoped only to Payroll and the specific LTK account.
  2. A separate, small monthly fee (e.g. a platform/referral fee)
     being netted directly against Amazon revenue at the point of
     deposit -- would explain a small, CONSISTENT shortfall differently
     than a missing-transaction explanation.
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

    print("=== Hypothesis 1: Amazon-related JournalEntry ===")
    query = "SELECT * FROM JournalEntry WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-06-30' MAXRESULTS 200"
    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED: {resp.text}\n")
    else:
        entries = resp.json().get("QueryResponse", {}).get("JournalEntry", [])
        matches = []
        for e in entries:
            haystack = (e.get("PrivateNote", "") + " ".join(
                (l.get("Description") or "") + " " + ((l.get("JournalEntryLineDetail") or {}).get("AccountRef") or {}).get("name", "")
                for l in e.get("Line", [])
            )).lower()
            if "amazon" in haystack:
                matches.append(e)
        if matches:
            print(f"FOUND {len(matches)} real journal entries referencing Amazon:")
            print(json.dumps(matches[0], indent=2))
        else:
            print(f"Checked {len(entries)} real journal entries (Jan-Jun 2026) -- zero reference Amazon.")
            print("This hypothesis is ruled out.")

    print("\n=== Hypothesis 2: a real Amazon fee account netted against revenue ===")
    query2 = "SELECT * FROM Purchase WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-06-30' MAXRESULTS 200"
    resp2 = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query2},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp2.status_code >= 400:
        print(f"FAILED: {resp2.text}")
    else:
        purchases = resp2.json().get("QueryResponse", {}).get("Purchase", [])
        fee_matches = []
        for p in purchases:
            for line in p.get("Line", []):
                detail = line.get("AccountBasedExpenseLineDetail", {})
                acct_name = (detail.get("AccountRef") or {}).get("name", "")
                desc = line.get("Description", "") or ""
                if "amazon" in (acct_name + " " + desc).lower():
                    fee_matches.append((p.get("TxnDate"), acct_name, line.get("Amount"), desc))
        if fee_matches:
            print(f"FOUND {len(fee_matches)} real Amazon-related Purchase line(s):")
            for date_, acct, amt, desc in fee_matches:
                print(f"  {date_}  {acct}  ${amt}  {desc!r}")
        else:
            print(f"Checked {len(purchases)} real Purchase transactions (Jan-Jun 2026) -- zero reference Amazon.")
            print("This hypothesis is also ruled out.")

    print("\n--- Next step ---")
    print("Paste this full output back. If both hypotheses come back empty,")
    print("the real explanation may need Katelyn's direct knowledge --")
    print("worth asking her the same way LTK's RewardStyle rename came up.")


if __name__ == "__main__":
    main()
