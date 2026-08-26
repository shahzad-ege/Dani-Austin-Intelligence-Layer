"""
discover_branded_content_fields.py — Finds which branded-content field
name(s) the live Instagram Graph API actually accepts for this account.

WHY THIS EXISTS: `is_branded_content` / `branded_partner_name` are columns
in social_posts, and the Claude Project instructions describe this as the
cleanest link between a post and Brand Partnership revenue -- but the
connector never actually requested any branded-content field from the API,
so all 162 posts have the schema default (false) and zero partner names.

Rather than guess a field name (this project has already burned several
cycles on guessed Meta/QuickBooks field names), this script asks the API
directly: it tries each candidate ONE AT A TIME and reports which are
accepted vs rejected. Meta rejects an unknown field with a clear error
naming it, so a rejection is informative rather than fatal.

USAGE:
    python discover_branded_content_fields.py

Then paste the output back so the connector can be updated with whatever
field name(s) actually work. Read-only -- writes nothing to the database.
"""

import os
import requests
from dotenv import load_dotenv

# Every other connector in this project loads .env via db.py before reading
# env vars. This is a standalone script that doesn't import db.py, so it has
# to do that itself -- without this, os.environ reads fail with a bare
# KeyError even when .env is correctly populated.
load_dotenv()

_missing = [
    name for name in ("META_SYSTEM_USER_TOKEN", "META_IG_USER_ID")
    if not os.environ.get(name)
]
if _missing:
    raise SystemExit(
        f"Missing or empty in .env: {_missing}\n"
        f"Run this from the connectors/ directory (where .env lives), and "
        f"confirm those values are set -- this script reads the same "
        f"credentials meta_connector.py uses."
    )

META_SYSTEM_USER_TOKEN = os.environ["META_SYSTEM_USER_TOKEN"]
META_IG_USER_ID = os.environ["META_IG_USER_ID"]

GRAPH_API_VERSION = "v25.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Candidate field names, from Meta's own docs, changelogs, and third-party
# references. Deliberately broad -- the point is to let the API tell us
# which are real rather than committing to one guess.
CANDIDATE_FIELDS = [
    "boost_eligibility_info",
    "branded_content_partner",
    "branded_content_partners",
    "branded_content_tag",
    "branded_content_tags",
    "is_branded_content",
    "paid_partnership",
    "paid_partnership_label",
    "sponsor_tags",
    "partner_tags",
    "collaborators",
    "is_paid_partnership",
    "media_product_type",
    "shortcode",
]


def try_field(field_name: str) -> tuple[bool, str]:
    """Requests a single field. Returns (accepted, detail)."""
    resp = requests.get(
        f"{GRAPH_BASE_URL}/{META_IG_USER_ID}/media",
        params={
            "fields": f"id,{field_name}",
            "limit": 3,
            "access_token": META_SYSTEM_USER_TOKEN,
        },
    )
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        # Report whether the field actually came back populated, not just
        # whether the request succeeded -- Meta silently omits fields it
        # accepts but won't serve (a pattern already hit twice in this
        # project, with follows_and_unfollows and QuickBooks columns).
        present = [d for d in data if field_name in d]
        if present:
            sample = {k: v for k, v in present[0].items() if k != "id"}
            return True, f"ACCEPTED and populated. Sample: {sample}"
        return True, "accepted, but silently omitted from the response (no data served)"
    try:
        msg = resp.json().get("error", {}).get("message", resp.text)
    except Exception:
        msg = resp.text
    return False, f"rejected: {msg}"


def main() -> None:
    print(f"Testing {len(CANDIDATE_FIELDS)} candidate branded-content field names")
    print(f"against IG account {META_IG_USER_ID} on Graph API {GRAPH_API_VERSION}\n")

    accepted_populated, accepted_empty, rejected = [], [], []

    for field in CANDIDATE_FIELDS:
        ok, detail = try_field(field)
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {field:32} {detail}")
        if ok and "populated" in detail:
            accepted_populated.append(field)
        elif ok:
            accepted_empty.append(field)
        else:
            rejected.append(field)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Accepted AND populated (use these):  {accepted_populated or 'none'}")
    print(f"Accepted but served no data:         {accepted_empty or 'none'}")
    print(f"Rejected outright:                   {rejected or 'none'}")
    print()
    if not accepted_populated:
        print("NOTE: if nothing came back populated, the most likely explanation is")
        print("that none of the last 25 posts are actually tagged as paid")
        print("partnerships -- which would be a real finding about the data, not")
        print("a code bug. Worth confirming against the Instagram app directly")
        print("before assuming a field-name problem.")


if __name__ == "__main__":
    main()
