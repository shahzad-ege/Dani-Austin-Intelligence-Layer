"""
diagnose_megaphone_404.py — Checks the real, exact URL being built
from your current .env values, and tests whether the network/podcast
IDs actually resolve, to isolate exactly which one is wrong.
"""

import os
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

MEGAPHONE_API_TOKEN = os.environ["MEGAPHONE_API_TOKEN"]
MEGAPHONE_NETWORK_ID = os.environ["MEGAPHONE_NETWORK_ID"]
MEGAPHONE_PODCAST_ID = os.environ["MEGAPHONE_PODCAST_ID"]

BASE_URL = "https://cms.megaphone.fm/api"


def main() -> None:
    print(f"MEGAPHONE_NETWORK_ID = {MEGAPHONE_NETWORK_ID!r}")
    print(f"MEGAPHONE_PODCAST_ID = {MEGAPHONE_PODCAST_ID!r}")

    url = f"{BASE_URL}/networks/{MEGAPHONE_NETWORK_ID}/podcasts/{MEGAPHONE_PODCAST_ID}/episodes"
    print(f"\nReal URL being called:\n{url}\n")

    resp = requests.get(url, headers={"Authorization": f"Token {MEGAPHONE_API_TOKEN}"}, params={"limit": 5}, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code >= 400:
        print(f"Body: {resp.text[:300]}")
    else:
        print(f"SUCCESS -- {len(resp.json())} real episode(s) returned")

    # Real, separate check: does the network_id alone resolve? Helps
    # isolate whether it's the network or the podcast id that's wrong.
    print("\n--- Checking whether the network_id alone resolves ---")
    network_url = f"{BASE_URL}/networks/{MEGAPHONE_NETWORK_ID}/podcasts"
    resp2 = requests.get(network_url, headers={"Authorization": f"Token {MEGAPHONE_API_TOKEN}"}, timeout=30)
    print(f"Status: {resp2.status_code}")
    if resp2.status_code < 400:
        podcasts = resp2.json()
        print(f"Network resolves -- {len(podcasts)} real podcast(s) under this network:")
        for p in podcasts[:10]:
            print(f"  id={p.get('id')}  title={p.get('title')}")
        if MEGAPHONE_PODCAST_ID not in [p.get("id") for p in podcasts]:
            print(f"\n*** MEGAPHONE_PODCAST_ID ({MEGAPHONE_PODCAST_ID!r}) is NOT in this list ***")
            print("This is very likely the real problem -- update .env with the correct id above.")
    else:
        print(f"Body: {resp2.text[:300]}")
        print("\nThe network_id itself doesn't resolve -- check MEGAPHONE_NETWORK_ID directly.")


if __name__ == "__main__":
    main()
