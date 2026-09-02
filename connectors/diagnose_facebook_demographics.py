"""
diagnose_facebook_demographics.py — BUG-2 from the Meta API Bug Report:
social_audience_demographics has 1,313 rows, all Instagram, zero Facebook.

Code review confirms this isn't a silent failure -- fetch_facebook_demographics()
doesn't exist at all. The connector only ever built Instagram's demographic
fetch. This is a real, genuine gap, not a previously-investigated dead end
(the earlier "page_fans rejected" finding was about the plain follower
COUNT metric, a different thing from the demographic BREAKDOWN fields
tested here).

WHY THIS IS A DIAGNOSTIC, NOT THE FULL FIX: Instagram's demographic
endpoint uses a modern metric+breakdown-parameter shape (see
fetch_instagram_demographics). Facebook's older-style Page Insights
demographic metrics (page_fans_gender_age, page_fans_country,
page_fans_city) have historically used a DIFFERENT response shape --
often a single flat object with combined keys like "F.25-34": 123 rather
than a breakdown array. Guessing at this shape and writing a parser blind
risks either crashing on real data or, worse, silently parsing something
wrong. This script captures the REAL raw payload first so the actual
parser can be built to match confirmed reality, not assumption.

Run this directly. Paste the full output back so the real fetch function
can be built against confirmed real behavior.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

META_SYSTEM_USER_TOKEN = os.environ["META_SYSTEM_USER_TOKEN"]
META_PAGE_ID = os.environ["META_PAGE_ID"]
GRAPH_BASE_URL = "https://graph.facebook.com/v25.0"

# UPDATE (Sep 2026): the original 4 candidates below were all confirmed
# rejected via a real diagnostic run -- (#100) invalid metric, the same
# error signature already seen for other deprecated fields in this
# project. Checked against Meta's own official Pages API changelog rather
# than guess at replacements:
#   - page_fans_city    -> REAL replacement confirmed: page_follows_city
#   - page_fans_country -> REAL replacement confirmed: page_follows_country
#     (both deprecated Nov 15, 2025, same wave as page_fans -> page_follows,
#     already handled elsewhere in this connector)
#   - page_fans_gender_age -> deprecated Mar 14, 2024, NO alternative listed.
#     Independently corroborated: Meta restricted age/gender demographic
#     access specifically for privacy reasons around that date -- this
#     looks genuinely gone, not renamed, but still worth one real
#     confirmation call rather than assuming from secondhand sources alone.
#   - page_fans_locale -> deprecated Nov 15, 2025, NO alternative listed.
#     Same treatment -- worth confirming directly, but likely genuinely
#     gone.
CANDIDATE_METRICS = [
    "page_follows_city",
    "page_follows_country",
    "page_fans_gender_age",  # kept despite likely being gone -- real confirmation over assumption
    "page_fans_locale",      # kept despite likely being gone -- real confirmation over assumption
]


def get_page_access_token() -> str:
    """Mirrors meta_connector.py's own page-token exchange."""
    resp = requests.get(
        f"{GRAPH_BASE_URL}/me/accounts",
        params={"access_token": META_SYSTEM_USER_TOKEN},
    )
    resp.raise_for_status()
    for page in resp.json().get("data", []):
        if page.get("id") == META_PAGE_ID:
            return page["access_token"]
    raise RuntimeError(f"Page {META_PAGE_ID} not found in /me/accounts -- check permissions")


def main() -> None:
    print("Getting Page access token...")
    page_token = get_page_access_token()
    print("Got it.\n")

    for metric in CANDIDATE_METRICS:
        print(f"=== Testing metric: {metric} ===")
        resp = requests.get(
            f"{GRAPH_BASE_URL}/{META_PAGE_ID}/insights",
            params={"metric": metric, "period": "lifetime", "access_token": page_token},
        )
        print(f"Status: {resp.status_code}")

        if resp.status_code >= 400:
            print(f"REJECTED. Error body: {resp.text}\n")
            continue

        payload = resp.json()
        print("Full raw response:")
        print(json.dumps(payload, indent=2))

        data = payload.get("data", [])
        if not data:
            print("ACCEPTED but returned empty data array -- may need a fan-count")
            print("threshold, or this specific field may be silently unavailable")
            print("despite not erroring (same pattern seen elsewhere in this project).")
        else:
            values = data[0].get("values", [])
            if values:
                print(f"\nPopulated! First value entry shape: {json.dumps(values[0], indent=2)}")
            else:
                print("ACCEPTED, data array present, but no 'values' inside it.")
        print()

    # Follow-up: page_follows_city/country were confirmed VALID metric
    # names (200, not rejected like the old page_fans_* names) but
    # returned empty for the default window, which turned out to be the
    # most recent ~2 days (2026-08-30 to 2026-09-01) -- decoded directly
    # from the response's own pagination URLs, not assumed. This tests
    # whether that's a processing lag specific to recent days, or the
    # metric is empty across the board regardless of date range.
    print("=" * 60)
    print("FOLLOW-UP: testing page_follows_city with an explicit, older")
    print("date range (60 days back) rather than the silent default window")
    print("=" * 60)
    import time
    until_ts = int(time.time())
    since_ts = until_ts - (60 * 86400)
    resp = requests.get(
        f"{GRAPH_BASE_URL}/{META_PAGE_ID}/insights",
        params={
            "metric": "page_follows_city",
            "period": "lifetime",
            "since": since_ts,
            "until": until_ts,
            "access_token": page_token,
        },
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code >= 400:
        print(f"REJECTED with explicit range too: {resp.text}")
    else:
        payload = resp.json()
        print(json.dumps(payload, indent=2))
        if payload.get("data"):
            print("\nPopulated with an explicit older range -- this points to a")
            print("processing lag on recent days specifically, not a fundamentally")
            print("broken/empty metric. Worth querying with a deliberate lag buffer")
            print("(e.g. always request through 3-4 days ago, not through today).")
        else:
            print("\nStill empty even with a 60-day explicit range. This suggests the")
            print("metric may be empty across the board for this Page -- possibly a")
            print("fan-count threshold, or a real Meta-side gap despite being a")
            print("technically valid, non-rejected metric name.")

    # Second follow-up: the metric kept paginating in narrow ~2-day
    # windows even with an explicit 60-day range and period=lifetime --
    # confirmed via two real runs, not a fluke. That pagination pattern is
    # a strong technical signal this metric behaves as a genuine
    # day-level time-series under the hood (like most regular Page
    # Insights metrics), not a true lifetime-cumulative one the way the
    # old page_fans_city was. Requesting period=lifetime may simply be
    # the wrong shape for this specific metric, regardless of date range.
    print("=" * 60)
    print("FOLLOW-UP 2: testing page_follows_city with period=day instead")
    print("of period=lifetime -- the metric's own pagination behavior")
    print("(narrow ~2-day windows even with a 60-day range) suggests it's")
    print("genuinely a day-level metric, and 'lifetime' may be the wrong")
    print("period value entirely for this one, not just an empty range.")
    print("=" * 60)
    resp = requests.get(
        f"{GRAPH_BASE_URL}/{META_PAGE_ID}/insights",
        params={
            "metric": "page_follows_city",
            "period": "day",
            "since": since_ts,
            "until": until_ts,
            "access_token": page_token,
        },
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code >= 400:
        print(f"REJECTED with period=day: {resp.text}")
    else:
        payload = resp.json()
        print(json.dumps(payload, indent=2)[:3000])
        data = payload.get("data", [])
        total_values = sum(len(d.get("values", [])) for d in data)
        if total_values > 0:
            print(f"\nPopulated! {total_values} value entries across {len(data)} data block(s).")
            print("period=day is the right shape -- lifetime was wrong for this metric.")
        else:
            print("\nStill empty even with period=day. At this point the most likely")
            print("explanation is a genuine Meta-side gap for this Page specifically")
            print("(despite the metric name itself being valid) -- worth treating")
            print("city/country as unavailable in practice, same as age/gender/locale,")
            print("even though they don't hard-reject like those do.")

    print("\n--- Next step ---")
    print("Paste this full output back. Whichever metrics show real populated")
    print("data (and their actual response shape) will be used to build the")
    print("real fetch_facebook_demographics() function -- matched to what's")
    print("actually true, not guessed at.")


if __name__ == "__main__":
    main()
