"""
find_youtube_channel_id.py — Looks up the real YouTube Channel ID
using the already-confirmed-working YOUTUBE_API_KEY, via the official
channels.list forHandle parameter (confirmed real and documented,
developers.google.com/youtube/v3/docs/channels/list).

Usage: python find_youtube_channel_id.py @thehandle
(the @ is optional -- forHandle accepts it either way)
"""

import os
import sys
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python find_youtube_channel_id.py @yourhandle")
        print("(find the real handle in the channel's own URL, e.g. youtube.com/@daniaustin)")
        sys.exit(1)

    handle = sys.argv[1]
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "id,snippet", "forHandle": handle, "key": YOUTUBE_API_KEY},
    )

    if resp.status_code >= 400:
        print(f"Status {resp.status_code}: {resp.text}")
        return

    items = resp.json().get("items", [])
    if not items:
        print(f"No channel found for handle {handle!r} -- double-check the exact handle from the channel's URL.")
        return

    channel = items[0]
    print(f"Real channel found: {channel['snippet']['title']}")
    print(f"\nYOUTUBE_CHANNEL_ID={channel['id']}")


if __name__ == "__main__":
    main()
