"""
diagnose_tiktok_video_list.py — Checks the RAW /business/video/list/
response directly, since fetch_video_metrics() summed to all-zero
despite the account having 1,721+ real uploads (per Social Blade).

Real, specific hypothesis this tests: TIKTOK_BUSINESS_ID is currently
set to the open_id from the token response -- confirmed to work for
the followers endpoint, but never independently confirmed for
video-specific endpoints, which may genuinely require a different
identifier.
"""

import os
import json
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
TIKTOK_REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]
TIKTOK_BUSINESS_ID = os.environ["TIKTOK_BUSINESS_ID"]

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


def refresh_access_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/tt_user/oauth2/refresh_token/",
        json={
            "client_id": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": TIKTOK_REFRESH_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def main() -> None:
    print("Refreshing access token...")
    access_token = refresh_access_token()
    print("Token refreshed.\n")

    print(f"Using TIKTOK_BUSINESS_ID: {TIKTOK_BUSINESS_ID}\n")

    resp = requests.get(
        f"{BASE_URL}/business/video/list/",
        headers={"Access-Token": access_token},
        params={"business_id": TIKTOK_BUSINESS_ID, "fields": '["video_views","likes","comments","shares","item_id","create_time"]'},
    )
    print(f"Status: {resp.status_code}\n")
    print("Full raw response:")
    print(json.dumps(resp.json(), indent=2))

    print("\n--- Next step ---")
    print("Paste this full output back. If the error mentions the business_id")
    print("being invalid/not found/unauthorized, that confirms open_id isn't")
    print("the right identifier for this endpoint specifically -- the real")
    print("business_id likely needs to come from a different call or the")
    print("TikTok Business Portal UI directly.")


if __name__ == "__main__":
    main()
