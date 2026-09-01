"""
check_airtable_schema.py — Diagnoses the Airtable 403
(INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND) by hitting the base SCHEMA
endpoint instead of the table itself. This is a different, lower-risk
operation than pulling records:

  - If this succeeds and lists real table names: the original 403 was
    about the TABLE NAME being wrong (typo, capitalization, trailing
    space) -- not a permissions/org-block issue at all. Compare the
    printed table names against "Master Tracking" exactly.
  - If this ALSO fails with the same INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND
    error: that's strong evidence of the org-level API block (Settings ->
    Integrations & development -> "Block API access to organization-owned
    bases and workspaces"), since even a basic metadata read is being
    refused.

Run with: python check_airtable_schema.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

base_id = os.environ.get("AIRTABLE_BASE_ID")
token = os.environ.get("AIRTABLE_API_KEY")

if not base_id or not token:
    print("ERROR: AIRTABLE_BASE_ID or AIRTABLE_API_KEY not found in .env")
    print(f"  AIRTABLE_BASE_ID present: {bool(base_id)}")
    print(f"  AIRTABLE_API_KEY present: {bool(token)}")
    sys.exit(1)

print(f"Checking schema for base: {base_id}\n")

resp = requests.get(
    f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
    headers={"Authorization": f"Bearer {token}"},
)

print(f"Status code: {resp.status_code}\n")

if resp.status_code == 200:
    data = resp.json()
    tables = data.get("tables", [])
    print("SUCCESS -- real table names in this base:")
    for table in tables:
        print(f"  - {table['name']!r}  (id: {table['id']})")
    print("\nCompare these EXACTLY against 'Master Tracking' -- check for")
    print("typos, capitalization, or extra spaces.")

    # If a specific table name is passed as an argument, show its full
    # field list too -- the schema endpoint already includes this per
    # table, no extra API call needed. Lets us confirm which of several
    # similarly-named tables (e.g. "Partnerships" vs "Home Partnerships")
    # actually matches our expected field shape (Invoice #, Status,
    # Platform, etc.) instead of guessing from the name alone.
    if len(sys.argv) > 1:
        target_name = sys.argv[1]
        match = next((t for t in tables if t["name"] == target_name), None)
        if not match:
            print(f"\nNo table found with the exact name {target_name!r}.")
        else:
            print(f"\n=== Fields in {target_name!r} ===")
            for field in match.get("fields", []):
                print(f"  - {field['name']!r}  (type: {field['type']})")
else:
    print("FAILED. Raw response body:")
    print(resp.text)
    print("\nIf this shows the SAME 'INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND'")
    print("error as before, that's strong evidence this is the org-level")
    print("API block, not a table-name or token-scope issue.")
