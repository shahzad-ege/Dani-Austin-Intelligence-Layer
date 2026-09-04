"""
diagnose_megaphone.py — Discovers the real Megaphone API response shape
before building the full connector, matching this project's established
discipline: confirmed endpoint/auth shape found via research (Spotify's
own Publisher Terms confirm "Megaphone API token(s)" as standard account
tooling; a real working example showed the endpoint URL and auth header),
but the exact field names WITHIN an episode response were not confirmed
by that research. Rather than guess field names and risk silently
parsing something wrong (the same mistake already made once this
project, with Facebook demographics), this captures the real payload
first.

SETUP NEEDED BEFORE RUNNING:
  1. Log into the Megaphone CMS (podcasters.spotify.com or
     cms.megaphone.fm, depending on how the account was set up)
  2. Find your API token: Account settings -> API (exact path may vary;
     Megaphone's UI has changed since being absorbed into Spotify's
     podcaster tools)
  3. Find your Network ID and Podcast ID -- both are visible in the CMS
     URL when viewing your podcast, e.g.
     cms.megaphone.fm/networks/{NETWORK_ID}/podcasts/{PODCAST_ID}
  4. Set these as environment variables:
       MEGAPHONE_API_TOKEN
       MEGAPHONE_NETWORK_ID
       MEGAPHONE_PODCAST_ID

Run with: python diagnose_megaphone.py
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

MEGAPHONE_API_TOKEN = os.environ["MEGAPHONE_API_TOKEN"]
MEGAPHONE_NETWORK_ID = os.environ["MEGAPHONE_NETWORK_ID"]
MEGAPHONE_PODCAST_ID = os.environ["MEGAPHONE_PODCAST_ID"]
BASE_URL = "https://cms.megaphone.fm/api"


def main() -> None:
    url = f"{BASE_URL}/networks/{MEGAPHONE_NETWORK_ID}/podcasts/{MEGAPHONE_PODCAST_ID}/episodes"
    print(f"Requesting: {url}\n")

    resp = requests.get(
        url,
        headers={"Authorization": f"Token {MEGAPHONE_API_TOKEN}"},
    )

    print(f"Status: {resp.status_code}\n")

    if resp.status_code >= 400:
        print(f"FAILED. Response body: {resp.text}")
        print("\nIf this is 401/403: check the token is correct and has")
        print("read access to this podcast specifically.")
        print("If this is 404: check the Network ID and Podcast ID --")
        print("both should be visible in the CMS URL when viewing the")
        print("podcast, not guessed.")
        return

    data = resp.json()

    if isinstance(data, list) and data:
        print(f"SUCCESS -- {len(data)} episode(s) returned in this page.")
        print("\nFull raw shape of the FIRST episode (this defines what")
        print("fields the real connector should extract):")
        print(json.dumps(data[0], indent=2))

        print("\n--- Field names found (top-level only) ---")
        for key in data[0].keys():
            print(f"  {key}")
    elif isinstance(data, list):
        print("SUCCESS but the episode list is empty. Confirm the")
        print("Podcast ID is correct and the podcast has real episodes.")
    else:
        print("Response is not a list -- may be a different shape than")
        print("expected (e.g. a wrapper object with pagination). Full")
        print("raw response:")
        print(json.dumps(data, indent=2))

    print("\n--- Next step ---")
    print("Paste this full output back. The real fetch_megaphone_episodes()")
    print("function will be built to match these confirmed real field")
    print("names -- downloads/plays/publish date etc. -- not guessed at.")


if __name__ == "__main__":
    main()
