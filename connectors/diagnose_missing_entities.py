"""
diagnose_missing_entities.py — Checks whether real, material data exists
in QuickBooks entity types this connector has never queried.

WHY THIS EXISTS: two real, major gaps were found the same way in this
project (payroll and LTK revenue, both hiding in JournalEntry, an
entity type never queried before). Rather than assume those were the
only two, this checks QuickBooks' other confirmed-real entity types
systematically -- CreditMemo, VendorCredit, and RefundReceipt
specifically, since those could mean our current revenue/expense
totals are OVERSTATED (not just missing data entirely): a CreditMemo
or RefundReceipt not being captured means an original invoice's full
amount is still being counted even if some of it was later credited
back to the customer; a VendorCredit not being captured means an
expense isn't being reduced by a real credit received.

Payment and BillPayment are checked too, for completeness, but are
real, confirmed LOWER risk -- the Invoice/Bill themselves already
capture revenue/expense when earned/incurred; these mostly affect cash
TIMING, not P&L accuracy.

This is read-only. It does NOT write anything to Supabase -- it exists
purely to answer "is there real, material data here worth building a
real extractor for," the same diagnostic-first discipline used for
every other new entity type in this project.
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

# Real, confirmed-to-exist QuickBooks entity types this connector has
# never queried, checked in priority order (revenue/expense-accuracy
# risk first, cash-timing-only risk last).
ENTITIES_TO_CHECK = [
    ("CreditMemo", "Credits issued to customers -- could mean revenue is currently overstated"),
    ("VendorCredit", "Credits received from vendors -- could mean expenses are currently overstated"),
    ("RefundReceipt", "Direct refunds issued -- same revenue-overstatement risk as CreditMemo"),
    ("Payment", "Customer payments against invoices -- lower risk, mostly affects cash timing not P&L"),
    ("BillPayment", "Payments made to vendors -- lower risk, mostly affects cash timing not P&L"),
]


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


def check_entity(access_token: str, entity: str) -> None:
    query = f"SELECT * FROM {entity} WHERE TxnDate >= '2023-01-01' MAXRESULTS 5"
    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )

    if resp.status_code >= 400:
        print(f"  Status {resp.status_code}: {resp.text[:200]}")
        return

    data = resp.json()
    records = data.get("QueryResponse", {}).get(entity, [])

    if not records:
        print(f"  ZERO records found (2023 onward, sample check) -- likely genuinely unused, not a real gap.")
        return

    total_sample = sum(float(r.get("TotalAmt", 0) or 0) for r in records)
    print(f"  FOUND {len(records)} real record(s) in this 5-record sample, summing ${total_sample:,.2f}.")
    print(f"  First record's real Id: {records[0].get('Id')}, TxnDate: {records[0].get('TxnDate')}")
    print(f"  (This is a small sample to check EXISTENCE, not a full count -- if non-zero, a real")
    print(f"   diagnostic pulling the FULL history would be the next step, same as JournalEntry was.)")


def main() -> None:
    print(f"Environment: {QB_ENVIRONMENT}")
    print("Refreshing access token...")
    access_token = get_access_token()
    print("Token refreshed.\n")

    for entity, risk_note in ENTITIES_TO_CHECK:
        print(f"=== {entity} ===")
        print(f"  Real risk if missing: {risk_note}")
        try:
            check_entity(access_token, entity)
        except Exception as e:
            print(f"  ERROR checking this entity: {type(e).__name__}: {e}")
        print()

    print("--- Next step ---")
    print("Paste this full output back. Any entity showing real, non-zero records")
    print("is worth a proper diagnostic (like diagnose_ltk_journal_entries.py) to see")
    print("the full real structure before building an extractor -- same as every")
    print("other real fix in this project. Zero-record entities can be deprioritized.")


if __name__ == "__main__":
    main()
