"""
diagnose_ltk_journal_entries.py — Checks whether LTK/RewardStyle
revenue is hiding in JournalEntry the same way payroll was.

WHY THIS EXISTS: Katelyn described recording LTK commission revenue
via "adjusting entries" -- real accounting terminology strongly
associated with journal entries specifically. Our existing
JournalEntry extraction (extract_journal_entry_lines in
qb_connector.py) is deliberately scoped to "Payroll:"-prefixed
accounts only, meaning even if LTK-related journal entries exist in
the real QuickBooks data, our own synced qb_da_transaction_lines would
never show them -- this connector has simply never looked.

This is read-only and does NOT write anything to Supabase. It exists
purely to answer one question: does LTK/RewardStyle-related revenue
exist in JournalEntry at all? If yes, a real, scoped extractor
(matching the same "Payroll:"-prefix-style safety reasoning) can be
built next. If no, this rules out one real hypothesis and the search
continues elsewhere.
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

    query = "SELECT * FROM JournalEntry WHERE TxnDate >= '2023-01-01' MAXRESULTS 1000"
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
    entries = data.get("QueryResponse", {}).get("JournalEntry", [])
    print(f"Status: {resp.status_code} -- {len(entries)} journal entries returned (2023 onward).\n")

    keywords = ["ltk", "reward", "liketoknow", "commission"]
    matches = []
    for entry in entries:
        haystack_parts = [entry.get("PrivateNote", ""), entry.get("DocNumber", "")]
        for line in entry.get("Line", []):
            haystack_parts.append(line.get("Description", "") or "")
            detail = line.get("JournalEntryLineDetail", {})
            haystack_parts.append((detail.get("AccountRef") or {}).get("name", ""))
        haystack = " ".join(haystack_parts).lower()
        if any(kw in haystack for kw in keywords):
            matches.append(entry)

    if not matches:
        print("ZERO of these entries reference LTK, RewardStyle, LikeToKnow, or 'commission'")
        print("anywhere in their notes, line descriptions, or account names.")
        print("\nThis rules out the 'hiding in a payroll-style journal entry' hypothesis --")
        print("worth telling Katelyn this specific idea was checked and ruled out, so the")
        print("search for where this revenue actually lives can focus elsewhere.")
        return

    print(f"FOUND {len(matches)} real journal entr{'y' if len(matches)==1 else 'ies'} matching LTK/commission keywords.\n")
    print("Full raw shape of the first match:")
    print(json.dumps(matches[0], indent=2))
    print("\n--- Next step ---")
    print("Paste this output back -- if this is genuinely LTK revenue, a real, scoped")
    print("extractor can be built the same way the payroll one was.")


if __name__ == "__main__":
    main()
