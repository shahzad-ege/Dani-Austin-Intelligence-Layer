"""
airtable_connector.py — Airtable connector for the Brand Partnerships base.

Pulls the partnerships pipeline (Project Tracking view) and writes it into
airtable_partnerships. This is the pipeline source of truth — reconciles to
qb_da_transaction_lines on invoice_no.

Requires (via env vars, sourced from 1Password at run time):
    AIRTABLE_API_KEY        -- personal access token, read scope is sufficient
    AIRTABLE_BASE_ID        -- the Partnerships base ID
    AIRTABLE_TABLE_NAME     -- the table/view name, e.g. "Project Tracking"

Open item carried from the framework doc: confirm the exact Airtable field
names below (FIELD_MAP) against the real base — these are best guesses from
the reporting spec and will need a one-time adjustment once we can see the
actual base schema.
"""

import os
import requests
from datetime import date

from models import AirtablePartnership
from writer import upsert_rows

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Project Tracking")

AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"

# Maps our column names -> Airtable field names. Adjust once the real base
# schema is confirmed; these are placeholders based on the reporting spec.
FIELD_MAP = {
    "deal_id": "Record ID",
    "invoice_no": "Invoice #",
    "status": "Status",
    "deliverable_platform": "Platform",
    "client": "Agency Source",
    "is_repeat": "Returning Partner",
    "gross_amt": "Gross Amount",
    "net_amt": "Net Amount",
    "month_committed": "Month Committed",
    "month_completed": "Month Completed",
}


def fetch_records() -> list[dict]:
    """Pulls all records from the Airtable table, paginating via offset."""
    records = []
    params = {"pageSize": 100}
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    while True:
        resp = requests.get(AIRTABLE_BASE_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset

    return records


def _parse_month(value: str | None) -> date | None:
    if not value:
        return None
    # Airtable date fields come back as ISO strings (YYYY-MM-DD or with time).
    return date.fromisoformat(value[:10])


def run() -> int:
    raw_records = fetch_records()

    parsed = []
    for rec in raw_records:
        fields = rec.get("fields", {})
        parsed.append(
            AirtablePartnership(
                deal_id=rec["id"],
                invoice_no=fields.get(FIELD_MAP["invoice_no"]),
                status=fields.get(FIELD_MAP["status"], "Unknown"),
                deliverable_platform=fields.get(FIELD_MAP["deliverable_platform"]),
                client=fields.get(FIELD_MAP["client"]),
                is_repeat=fields.get(FIELD_MAP["is_repeat"]),
                gross_amt=fields.get(FIELD_MAP["gross_amt"]),
                net_amt=fields.get(FIELD_MAP["net_amt"]),
                month_committed=_parse_month(fields.get(FIELD_MAP["month_committed"])),
                month_completed=_parse_month(fields.get(FIELD_MAP["month_completed"])),
            )
        )

    return upsert_rows("airtable_partnerships", [p.to_row() for p in parsed])


if __name__ == "__main__":
    count = run()
    print(f"Airtable connector: upserted {count} partnership records.")
