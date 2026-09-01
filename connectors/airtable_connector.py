"""
airtable_connector.py — Airtable connector for the Brand Partnerships base.

Pulls the partnerships pipeline from the "Partnerships" table and writes it
into airtable_partnerships.

Requires (via env vars):
    AIRTABLE_API_KEY        -- personal access token (Airtable deprecated
                                API keys in Feb 2024; this holds a PAT
                                despite the variable name)
    AIRTABLE_BASE_ID        -- the Partnerships base ID
    AIRTABLE_TABLE_NAME     -- defaults to "Partnerships", CONFIRMED against
                                the real base schema (not a guess anymore --
                                "Master Tracking" and "Project Tracking"
                                were both wrong guesses tried earlier)

FIELD_MAP below is CONFIRMED against the real base's actual field list
(fetched via check_airtable_schema.py), not guessed from a reporting spec.
Two real corrections from the original guesses: "Invoice #" -> "Invoice
Number", "Agency Source" -> "Client" (a real, direct field match).
"Platform" doesn't exist at all -- "Deliverables" is the closest real
match for deliverable_platform. "Returning Partner" (is_repeat) has no
real analog in this base at all -- that field will always come back None,
not a bug, just genuinely unavailable data.

Real field also found that wasn't in original scope: "In QBO" (checkbox)
-- an explicit signal for whether a deal has been recorded in QuickBooks,
a better reconciliation signal than the previously-unconfirmed doc_num/
invoice_no join.
"""

import os
import requests
from datetime import date, datetime

from models import AirtablePartnership
from writer import upsert_rows

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Partnerships")

AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"

# Confirmed against the real base's actual field list -- not guessed.
FIELD_MAP = {
    "invoice_no": "Invoice Number",
    "status": "Status",
    "deliverable_platform": "Deliverables",
    "client": "Client",
    # "is_repeat" deliberately has NO entry -- no real field for this
    # exists in the base. Always comes back None. Not a bug.
    "gross_amt": "Gross Amt",
    "net_amt": "Net Amt",
    "month_committed": "Month Committed",
    "month_completed": "Month Completed",
    "in_qbo": "In QBO",
    "invoice_status": "Invoice Status",
    "agreement_status": "Agreement Status",
}


def fetch_records() -> list[dict]:
    """Pulls all records from the Airtable table, paginating via offset."""
    records = []
    params = {"pageSize": 100}
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    while True:
        resp = requests.get(AIRTABLE_BASE_URL, headers=headers, params=params)
        if resp.status_code >= 400:
            print(f"[airtable] API error response body: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset

    return records


def _parse_month(value) -> date | None:
    """
    Month Committed / Month Completed are typed as singleLineText in the
    REAL base, not a proper Airtable date field -- confirmed via the
    schema check, not assumed. That means free text, not a guaranteed ISO
    string.

    Confirmed against a real production run (1,351 records): the
    OVERWHELMING majority of values follow a consistent "Month YYYY"
    pattern (e.g. "January 2021", "August 2023") -- genuinely parseable,
    just not ISO. Handling this recovers the large majority of what would
    otherwise be silently dropped.

    Deliberately NOT handled, and correctly stays null: bare month names
    with no year at all ("June", "November") -- there is no way to know
    which year is meant, and guessing one would be fabricating data, not
    parsing it. A handful of values in the real data also look like
    source-side typos (e.g. "September 22024", "September 2033" likely
    meaning 2023, "January 20" likely truncated) -- these are also left
    null rather than guessed at; that's a data-quality issue in the
    source Airtable base itself, not something to silently "fix" here.
    """
    if not value:
        return None
    text = str(value).strip()

    # Try full ISO first (in case a real date field's raw value ever
    # comes through this path).
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    # Try "Month YYYY" (e.g. "January 2021") -- the dominant real pattern.
    for fmt in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            result = date(parsed.year, parsed.month, 1)
            # Flag, don't discard: a suspiciously-far-future year (e.g.
            # "September 2033") is likely a source-side typo, but the code
            # has no legitimate way to know that for certain -- silently
            # nulling it would just be a different kind of guessing.
            # Parse it as literally stated, and let the caller decide
            # whether to surface the flag.
            if result.year > date.today().year + 2:
                print(f"[airtable] NOTE: parsed {text!r} as {result} -- unusually far in the future, worth a human double-check (not auto-corrected)")
            return result
        except ValueError:
            continue

    return None


def _get_checkbox(fields: dict, key: str) -> bool:
    """
    Airtable's API OMITS unchecked checkbox fields from the response
    entirely -- confirmed directly from Airtable's own support docs:
    "All returned records do not include any fields with 'empty' values."
    A checked box returns True; an unchecked one returns nothing at all,
    not False. Using fields.get() directly would store this as NULL
    (genuinely unknown) when it almost always means "definitely
    unchecked." This distinguishes the two correctly -- only real
    checkbox fields should use this, not text/select fields where an
    absent value genuinely does mean "unknown," not "false."
    """
    return bool(fields.get(key, False))


def run() -> int:
    raw_records = fetch_records()

    parsed = []
    unparseable_dates = 0

    for rec in raw_records:
        fields = rec.get("fields", {})

        month_committed_raw = fields.get(FIELD_MAP["month_committed"])
        month_completed_raw = fields.get(FIELD_MAP["month_completed"])
        month_committed = _parse_month(month_committed_raw)
        month_completed = _parse_month(month_completed_raw)

        if month_committed_raw and month_committed is None:
            print(f"[airtable] Could not parse Month Committed value {month_committed_raw!r} on record {rec['id']} -- left null, not guessed")
            unparseable_dates += 1
        if month_completed_raw and month_completed is None:
            print(f"[airtable] Could not parse Month Completed value {month_completed_raw!r} on record {rec['id']} -- left null, not guessed")
            unparseable_dates += 1

        parsed.append(
            AirtablePartnership(
                deal_id=rec["id"],
                invoice_no=fields.get(FIELD_MAP["invoice_no"]),
                status=fields.get(FIELD_MAP["status"], "Unknown"),
                deliverable_platform=fields.get(FIELD_MAP["deliverable_platform"]),
                client=fields.get(FIELD_MAP["client"]),
                is_repeat=None,  # no real field exists for this
                gross_amt=fields.get(FIELD_MAP["gross_amt"]),
                net_amt=fields.get(FIELD_MAP["net_amt"]),
                month_committed=month_committed,
                month_completed=month_completed,
                in_qbo=_get_checkbox(fields, FIELD_MAP["in_qbo"]),
                invoice_status=fields.get(FIELD_MAP["invoice_status"]),
                agreement_status=fields.get(FIELD_MAP["agreement_status"]),
            )
        )

    if unparseable_dates:
        print(f"[airtable] {unparseable_dates} date value(s) couldn't be parsed -- left null rather than guessed, see log above for which records")

    return upsert_rows("airtable_partnerships", [p.to_row() for p in parsed])


if __name__ == "__main__":
    count = run()
    print(f"Airtable connector: upserted {count} partnership records.")
