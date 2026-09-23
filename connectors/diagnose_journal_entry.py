"""
diagnose_journal_entry.py — Confirms the real, live structure of
QuickBooks JournalEntry records before building any extraction logic.

WHY THIS EXISTS: reconciling against a real QuickBooks P&L export (Sep
2026) found that Salaries & Wages -- the single largest expense line
in the entire business ($360,464.13 for the year) -- doesn't exist
anywhere in qb_da_transaction_lines. Root cause, confirmed by reading
qb_connector.py directly: ENTITY_CONFIG only queries Purchase, Bill,
Invoice, SalesReceipt, and Deposit. It has never queried JournalEntry
-- and payroll processors (Gusto, ADP, etc.) almost universally post
payroll runs as journal entries, not bills.

This script does NOT assume JournalEntry's real structure. Journal
entries have a fundamentally different shape from Purchase/Bill (each
line is either a debit or a credit, referencing an account directly,
rather than a simple expense-line-with-detail structure) -- but the
EXACT field names for this need to be confirmed against a real
response before writing any real extraction code, same diagnostic-
first discipline used for every other new entity/endpoint in this
project.

Reuses the exact same OAuth/query mechanism already proven correct in
qb_connector.py -- this is only a read-only query, so it's safe to run
without affecting the regular sync in any way.
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
    """Same refresh mechanism as qb_connector.py, reading the current
    stored token from Supabase (not the possibly-stale .env value)."""
    from db import get_client

    client = get_client()
    result = client.table("qb_oauth_credentials").select("*").eq("realm_id", QB_REALM_ID).execute()
    if not result.data:
        raise RuntimeError(
            "No stored refresh token found in qb_oauth_credentials for this "
            "realm. The regular qb_connector.py sync needs to have run at "
            "least once already for this diagnostic to have a valid token to use."
        )
    current_refresh_token = result.data[0]["refresh_token"]

    resp = requests.post(
        QB_TOKEN_URL,
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        data={"grant_type": "refresh_token", "refresh_token": current_refresh_token},
        headers={"Accept": "application/json"},
    )
    if resp.status_code >= 400:
        print(f"FAILED to refresh token ({resp.status_code}): {resp.text}")
        raise RuntimeError("Token refresh failed -- see response above.")

    token_data = resp.json()

    # Persist the rotated token immediately, matching qb_connector.py's
    # own discipline -- otherwise this diagnostic run would silently
    # invalidate the token for the next real scheduled sync.
    from writer import upsert_rows
    upsert_rows("qb_oauth_credentials", [{"realm_id": QB_REALM_ID, "refresh_token": token_data["refresh_token"]}])

    return token_data["access_token"]


def main() -> None:
    print(f"Environment: {QB_ENVIRONMENT}")
    print("Refreshing access token...")
    access_token = get_access_token()
    print("Token refreshed successfully.\n")

    # REAL GAP FOUND after the first diagnostic run: the initial 3
    # results happened to be a contractor payment (JD Rodgers), not
    # payroll. That confirms JournalEntry EXISTS and has a debit/credit
    # line structure, but does NOT yet confirm Salaries & Wages
    # specifically flows through it. Searching more broadly and
    # explicitly checking each entry's lines for a Salaries & Wages
    # reference, rather than assuming the first few generic results are
    # representative of the one account we actually need.
    # Scoped to 2026 specifically (matching the exact WHERE TxnDate
    # pattern already proven working in qb_connector.py) rather than
    # using an ORDERBY clause not yet validated anywhere in this
    # codebase -- safer to stick to confirmed-working query syntax.
    query = "SELECT * FROM JournalEntry WHERE TxnDate >= '2026-01-01' MAXRESULTS 100"
    print(f"Querying: {query}\n")

    resp = requests.get(
        f"{QB_API_BASE}/v3/company/{QB_REALM_ID}/query",
        params={"query": query},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )

    if resp.status_code >= 400:
        print(f"Status: {resp.status_code}")
        print(f"FAILED. Response body: {resp.text}")
        return

    data = resp.json()
    entries = data.get("QueryResponse", {}).get("JournalEntry", [])
    print(f"Status: {resp.status_code} -- {len(entries)} real journal entries returned in this batch.\n")

    payroll_entries = []
    for entry in entries:
        for line in entry.get("Line", []):
            account_name = line.get("JournalEntryLineDetail", {}).get("AccountRef", {}).get("name", "")
            if "salar" in account_name.lower() or "wage" in account_name.lower():
                payroll_entries.append(entry)
                break

    if not payroll_entries:
        print("ZERO of these 100 most-recent journal entries reference a")
        print("Salaries & Wages (or similarly named) account on any line.")
        print("This is itself a real, important finding -- it would mean")
        print("payroll either isn't posted via JournalEntry at all, or is")
        print("posted so infrequently that none appear in the 100 most")
        print("recent entries. Worth checking a WIDER date range, or")
        print("asking Katelyn directly how payroll actually gets entered.")
        print("\nFor reference, here's what a NON-payroll journal entry")
        print("looks like in this data (confirms the general Line/")
        print("JournalEntryLineDetail structure, just not the payroll case):")
        if entries:
            print(json.dumps(entries[0], indent=2))
        return

    print(f"FOUND {len(payroll_entries)} real journal entr{'y' if len(payroll_entries)==1 else 'ies'} referencing Salaries & Wages.\n")
    print("Full raw shape of the FIRST matching entry:")
    print(json.dumps(payroll_entries[0], indent=2))

    print("\n--- Next step ---")
    print("Paste this full output back. The real extraction logic will")
    print("be built to match these confirmed real field names -- not")
    print("guessed at from the earlier non-payroll example.")


if __name__ == "__main__":
    main()
