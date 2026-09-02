"""
diagnose_tiktok_social_blade.py — Diagnoses the DA_Data_Scrub_Report finding
that TikTok Social Blade values (followers, likes, uploads) are static --
exactly one distinct value across 13 days.

The connector code itself looks correct (calls the real endpoint fresh each
day, same as Instagram/Facebook which DO update). This script exists to
see the FULL raw response rather than guess at the cause -- specifically
checking:

  1. Does the response include a "last updated" / timestamp field showing
     whether SOCIAL BLADE'S OWN data is stale (their scrape of TikTok
     hasn't refreshed), vs. our side calling a cached/wrong endpoint?
  2. Does the credits balance actually decrement on repeated calls? If not,
     that's evidence we're hitting a cached response, not a fresh one.
  3. Are there OTHER fields in the payload that DO vary day to day, which
     would prove the call itself is live but only these 3 specific fields
     are frozen?

Run twice, at least a few minutes apart, and compare the two outputs
directly -- a single run can't tell you whether it's static.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

SOCIALBLADE_CLIENT_ID = os.environ["SOCIALBLADE_CLIENT_ID"]
SOCIALBLADE_TOKEN = os.environ["SOCIALBLADE_TOKEN"]
SOCIALBLADE_BASE_URL = "https://matrix.sbapis.com/b"

HANDLE = "thedaniaustin"


def main() -> None:
    resp = requests.get(
        f"{SOCIALBLADE_BASE_URL}/tiktok/statistics",
        headers={"clientid": SOCIALBLADE_CLIENT_ID, "token": SOCIALBLADE_TOKEN},
        params={"query": HANDLE},
    )

    print(f"Status code: {resp.status_code}\n")

    if resp.status_code >= 400:
        print("FAILED. Raw response body:")
        print(resp.text)
        return

    payload = resp.json()
    print("FULL raw response payload:")
    print(json.dumps(payload, indent=2))

    credits = payload.get("info", {}).get("credits", {}).get("available")
    print(f"\nCredits remaining after this call: {credits}")
    print("(Compare this number against the previous run's credits -- if it")
    print("hasn't decreased, this call may be serving a cached response)")

    # Look for any timestamp/last-updated field at any level of the payload
    def find_timestamp_fields(obj, path=""):
        found = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if "time" in k.lower() or "date" in k.lower() or "updated" in k.lower():
                    found.append((f"{path}.{k}", v))
                found.extend(find_timestamp_fields(v, f"{path}.{k}"))
        return found

    timestamps = find_timestamp_fields(payload)
    if timestamps:
        print("\nTimestamp-like fields found in the response:")
        for path, val in timestamps:
            print(f"  {path}: {val}")
    else:
        print("\nNo timestamp/last-updated field found anywhere in the response --")
        print("Social Blade's payload gives no direct way to tell if their own")
        print("TikTok data is fresh or stale from this field alone.")

    print("\n--- What to do with this output ---")
    print("Save this full output. Run this script again in a few minutes or")
    print("tomorrow, and diff the two payloads directly. If EVERYTHING matches")
    print("(not just followers/likes/uploads), that's strong evidence Social")
    print("Blade's own TikTok scrape is stale, not a bug in our connector. If")
    print("other fields differ but these three don't, that points somewhere")
    print("more specific worth following up with Social Blade support.")


if __name__ == "__main__":
    main()
