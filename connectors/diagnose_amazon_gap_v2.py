"""
diagnose_amazon_gap_v2.py — More targeted than the first attempt.

WHY THIS EXISTS: the first Amazon gap diagnostic searched broadly for
the WORD "amazon" in JournalEntry and Purchase -- which caught real but
unrelated data (Amazon.com vendor purchases, a gift card giveaway),
not anything touching the actual "Amazon Platform Affiliate Revenue"
account. This time searches for the EXACT account name specifically,
across JournalEntry and CreditMemo -- the two entity types that have
already been proven to hide real financial activity in this project
(payroll, LTK, and Bad Debt/revenue credits respectively).

Real hypothesis this specifically tests: a CreditMemo reducing
previously-recognized Amazon revenue by exactly $1,500/month would
explain a precise, recurring shortfall far better than a missing
transaction would.
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

TARGET_ACCOUNT = "Amazon Platform Affiliate Revenue"


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


def check_journal_entries(access_token: str) -> None:
    print("=== JournalEntry: searching for the EXACT account name ===")
    query = "SELECT * FROM JournalEntry WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-07-31' MAXRESULTS 500"
    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED: {resp.text}\n")
        return

    entries = resp.json().get("QueryResponse", {}).get("JournalEntry", [])
    matches = []
    for e in entries:
        for line in e.get("Line", []):
            acct = ((line.get("JournalEntryLineDetail") or {}).get("AccountRef") or {}).get("name", "")
            if acct == TARGET_ACCOUNT:
                matches.append(e)
                break

    if matches:
        print(f"FOUND {len(matches)} real journal entries touching '{TARGET_ACCOUNT}' directly:")
        print(json.dumps(matches[0], indent=2))
    else:
        print(f"Checked {len(entries)} real journal entries (Jan-Jul 2026) -- zero touch this exact account.")


def check_credit_memos(access_token: str) -> None:
    print("\n=== CreditMemo: searching for the EXACT account name ===")
    query = "SELECT * FROM CreditMemo WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-07-31' MAXRESULTS 500"
    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED: {resp.text}\n")
        return

    records = resp.json().get("QueryResponse", {}).get("CreditMemo", [])
    matches = []
    for r in records:
        for line in r.get("Line", []):
            detail = line.get("SalesItemLineDetail") or {}
            acct = (detail.get("ItemAccountRef") or {}).get("name", "")
            item = (detail.get("ItemRef") or {}).get("name", "")
            if TARGET_ACCOUNT.lower() in acct.lower() or "amazon" in item.lower():
                matches.append(r)
                break

    if matches:
        print(f"FOUND {len(matches)} real credit memo(s) touching Amazon revenue:")
        print(json.dumps(matches[0], indent=2))
    else:
        print(f"Checked {len(records)} real credit memos (Jan-Jul 2026) -- zero touch Amazon revenue.")


def check_amazon_item_details(access_token: str) -> None:
    """Real check: does the Invoice line item itself carry any fee or
    discount detail that isn't showing up as its own transaction?"""
    print("\n=== Invoice: checking real line-item detail for hidden fees/discounts ===")
    query = "SELECT * FROM Invoice WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-01-31' MAXRESULTS 10"
    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED: {resp.text}")
        return

    invoices = resp.json().get("QueryResponse", {}).get("Invoice", [])
    for inv in invoices:
        for line in inv.get("Line", []):
            detail = line.get("SalesItemLineDetail") or {}
            item_name = (detail.get("ItemRef") or {}).get("name", "")
            if "amazon" in item_name.lower():
                print(f"Real January Amazon invoice line found -- full detail:")
                print(json.dumps(line, indent=2))
                print(f"Full invoice DiscountAmt/discount fields: "
                      f"{json.dumps({k: v for k, v in inv.items() if 'discount' in k.lower() or 'Discount' in k}, indent=2)}")
                return
    print("No January Amazon invoice line found in this sample.")


def main() -> None:
    print(f"Environment: {QB_ENVIRONMENT}")
    print("Refreshing access token...")
    access_token = get_access_token()
    print("Token refreshed.\n")

    check_journal_entries(access_token)
    check_credit_memos(access_token)
    check_amazon_item_details(access_token)

    print("\n--- Next step ---")
    print("Paste this full output back. If all three come back empty, this")
    print("genuinely needs Katelyn's direct knowledge -- the same way LTK's")
    print("RewardStyle rename only became clear from her, not from more searching.")


if __name__ == "__main__":
    main()
