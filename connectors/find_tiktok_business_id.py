"""
find_tiktok_business_id.py — Uses your now-working TikTok credentials
to find the real Business Account ID, rather than guessing at it.

WHY THIS EXISTS: tiktok_connector.py needs TIKTOK_BUSINESS_ID, but this
is a distinct value from the open_id returned by the standard OAuth
flow -- it's specific to TikTok's Business Account API (the one this
connector's business_id= parameters actually call). Rather than assume
which field is the right one, this queries TikTok's real user info
endpoint directly and prints the complete response.
"""

import os
import json
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
TIKTOK_REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"


def refresh_access_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": TIKTOK_REFRESH_TOKEN,
        },
    )
    if resp.status_code >= 400:
        print(f"FAILED to refresh access token ({resp.status_code}): {resp.text}")
        raise RuntimeError("Token refresh failed -- see response above.")
    data = resp.json()
    print(f"Access token refreshed successfully. Real open_id: {data.get('open_id')}")
    return data["access_token"]


def main() -> None:
    print("Refreshing access token using your real, working refresh token...\n")
    access_token = refresh_access_token()

    print("\nQuerying real user info endpoint for all available fields...\n")
    resp = requests.get(
        USER_INFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "open_id,union_id,display_name,username,avatar_url"},
    )

    if resp.status_code >= 400:
        print(f"Status: {resp.status_code}")
        print(f"FAILED: {resp.text}")
        return

    print(f"Status: {resp.status_code}\n")
    data = resp.json()
    print("Full real response:")
    print(json.dumps(data, indent=2))

    print("\n--- Next step ---")
    print("Paste this full output back. None of these fields may directly")
    print("say 'business_id' -- if that's the case, it likely needs to come")
    print("from the TikTok Business Portal (business-api.tiktok.com) directly,")
    print("not this standard user-info endpoint, and we'll look there instead.")


if __name__ == "__main__":
    main()
