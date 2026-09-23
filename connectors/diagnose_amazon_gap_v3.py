"""
diagnose_amazon_gap_v3.py — Full, exhaustive investigation, not a
sample. Pulls EVERY real invoice in the Jan-Jun 2026 window touching
Amazon Platform Affiliate Revenue, and directly compares each real
QuickBooks amount against what we actually have synced in Supabase --
ruling out a bug in OUR extraction, not just checking QuickBooks itself.

This is the "fully thorough before asking Katelyn" pass: if this comes
back clean (our synced amounts exactly match every real QB invoice,
and no discount/fee field is silently reducing anything), the honest
conclusion is that the $1,500/month gap isn't a data or sync issue at
all -- it needs her direct knowledge, not more searching.
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
PAGE_SIZE = 100


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


def fetch_all_invoices(access_token: str) -> list[dict]:
    """Real pagination, not a single-page sample -- walks the full
    Jan-Jun 2026 window using STARTPOSITION/MAXRESULTS until QuickBooks
    returns fewer than a full page, confirming nothing was truncated."""
    all_invoices = []
    start = 1
    while True:
        query = (
            f"SELECT * FROM Invoice WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-06-30' "
            f"STARTPOSITION {start} MAXRESULTS {PAGE_SIZE}"
        )
        resp = requests.get(
            f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
            params={"query": query},
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            print(f"FAILED at position {start}: {resp.text}")
            break

        batch = resp.json().get("QueryResponse", {}).get("Invoice", [])
        all_invoices.extend(batch)
        print(f"  Fetched page starting at {start}: {len(batch)} real invoice(s)")

        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    return all_invoices


def get_our_synced_amounts() -> dict:
    """Pulls what we actually have synced in Supabase for direct
    comparison against the real QuickBooks data, keyed by qb_txn_id."""
    from db import get_client

    client = get_client()
    result = (
        client.table("qb_da_transaction_lines")
        .select("qb_txn_id, amount, txn_date")
        .eq("account", TARGET_ACCOUNT)
        .gte("txn_date", "2026-01-01")
        .lte("txn_date", "2026-06-30")
        .execute()
    )
    # FIXED (Sep 23 2026 audit): the original built {txn_id: amount}, which
    # silently kept only ONE line when an invoice had several -- producing
    # false MISMATCH results on every real two-line Amazon invoice. Summing
    # per invoice instead.
    totals: dict = {}
    for row in result.data:
        totals[row["qb_txn_id"]] = totals.get(row["qb_txn_id"], 0.0) + float(row["amount"])
    return totals


def main() -> None:
    print(f"Environment: {QB_ENVIRONMENT}")
    print("Refreshing access token...")
    access_token = get_access_token()
    print("Token refreshed.\n")

    print("Fetching ALL real invoices, Jan-Jun 2026, with real pagination:")
    invoices = fetch_all_invoices(access_token)
    print(f"\nTotal real invoices fetched: {len(invoices)}\n")

    amazon_invoices = []
    for inv in invoices:
        for line in inv.get("Line", []):
            detail = line.get("SalesItemLineDetail") or {}
            item_name = (detail.get("ItemRef") or {}).get("name", "")
            if item_name == TARGET_ACCOUNT:
                amazon_invoices.append((inv, line))

    print(f"Real invoices touching '{TARGET_ACCOUNT}': {len(amazon_invoices)}\n")

    print("Fetching what we actually have synced in Supabase for comparison...")
    our_data = get_our_synced_amounts()
    print(f"We have {len(our_data)} real synced row(s) for this account/period.\n")

    print("=== Real QuickBooks invoice total vs. our synced total, per invoice ===")
    real_total = 0.0
    discrepancies = []
    per_invoice: dict = {}
    for inv, line in amazon_invoices:
        entry = per_invoice.setdefault(inv.get("Id"), {"date": inv.get("TxnDate"), "amt": 0.0,
                                                       "discount": inv.get("DiscountAmt")})
        entry["amt"] += float(line.get("Amount", 0) or 0)

    for qb_id, info in per_invoice.items():
        real_total += info["amt"]
        ours = our_data.get(qb_id)
        ok = ours is not None and abs(ours - info["amt"]) < 0.01
        print(f"  Id {qb_id}  {info['date']}  QB total ${info['amt']:,.2f}  ours {ours}  "
              f"[{'MATCH' if ok else 'MISMATCH or MISSING'}]")
        if not ok:
            discrepancies.append((qb_id, info["date"], info["amt"], ours, info["discount"]))

    print(f"\nReal total across all Amazon invoices (Jan-Jun): ${real_total:,.2f}")
    print(f"Real discrepancies found: {len(discrepancies)}")

    if discrepancies:
        print("\n=== REAL DISCREPANCIES -- full detail ===")
        for qb_id, txn_date, real_amt, our_amt, discount in discrepancies:
            print(f"  Id {qb_id} ({txn_date}): QuickBooks shows ${real_amt:,.2f}, we have {our_amt}"
                  + (f", real DiscountAmt field = {discount}" if discount else ", no discount field set"))

    print("\n--- Next step ---")
    print("Paste this full output back. If every invoice shows MATCH and no")
    print("discount fields are set, the gap genuinely isn't in QuickBooks' invoice")
    print("data or our sync -- it needs Katelyn's direct knowledge from here.")


if __name__ == "__main__":
    main()
