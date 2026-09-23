"""
backfill_tiktok_videos.py — Full, paginated backfill of per-video
TikTok metrics via the Business API (business_organic flow).

WHY THIS EXISTS: fetch_video_metrics() in the regular connector only
ever fetches ONE page and sums it into a single daily aggregate --
confirmed via a live call that the real response includes
"has_more": true, meaning the vast majority of real video history has
never actually been pulled. This is time-sensitive: enrichment fields
(likes/comments/shares) go null after ~7 days of no engagement on a
post, and data stops updating 365 days post-publish -- the longer this
waits, the more real historical detail is permanently lost.

Pagination confirmed via TikTok's own consistent documentation across
every API variant checked: "cursor" (an int64 UTC-ms timestamp) and
"max_count" are the real parameter names. The real response already
returns "cursor" and "has_more", confirming the request accepts a
matching "cursor" to continue.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
TIKTOK_REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]
TIKTOK_BUSINESS_ID = os.environ["TIKTOK_BUSINESS_ID"]

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"
MAX_COUNT = 20  # confirmed real ceiling per TikTok's own documentation
MAX_PAGES = 200  # real safety cap -- stops runaway pagination if has_more never clears


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


def fetch_all_videos(access_token: str) -> list[dict]:
    """Real pagination, not a single-page sample. Walks every page
    until has_more is false or the real safety cap is hit."""
    all_videos: list[dict] = []
    cursor = None
    page = 0

    while page < MAX_PAGES:
        page += 1
        params = {
            "business_id": TIKTOK_BUSINESS_ID,
            "fields": '["video_views","likes","comments","shares","item_id","create_time"]',
            "max_count": MAX_COUNT,
        }
        if cursor is not None:
            params["cursor"] = cursor

        resp = requests.get(f"{BASE_URL}/business/video/list/", headers={"Access-Token": access_token}, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        videos = data.get("videos", [])
        all_videos.extend(videos)
        print(f"  Page {page}: {len(videos)} real video(s), running total {len(all_videos)}")

        has_more = data.get("has_more", False)
        cursor = data.get("cursor")
        if not has_more or cursor is None:
            break

        time.sleep(0.5)  # real, conservative rate-limit courtesy, not documented as required

    if page >= MAX_PAGES:
        print(f"  WARNING: hit the {MAX_PAGES}-page safety cap -- has_more may still be true. "
              f"Real video count may be incomplete; re-run if needed.")

    return all_videos


def main() -> None:
    print("Refreshing access token...")
    access_token = refresh_access_token()
    print("Token refreshed.\n")

    print("Fetching ALL real videos, with real pagination:")
    videos = fetch_all_videos(access_token)
    print(f"\nTotal real videos fetched: {len(videos)}\n")

    if not videos:
        print("No real videos returned -- nothing to write.")
        return

    rows = []
    for v in videos:
        item_id = v.get("item_id")
        if not item_id:
            continue
        create_time_raw = v.get("create_time")
        create_time_iso = None
        if create_time_raw:
            try:
                create_time_iso = datetime.fromtimestamp(int(create_time_raw), tz=timezone.utc).isoformat()
            except (ValueError, TypeError):
                pass
        rows.append({
            "item_id": item_id,
            "create_time": create_time_iso,
            "video_views": int(v.get("video_views") or 0),
            "likes": int(v.get("likes") or 0),
            "comments": int(v.get("comments") or 0),
            "shares": int(v.get("shares") or 0),
        })

    from writer import upsert_rows
    written = upsert_rows("tiktok_video_metrics", rows)
    print(f"Wrote {written} real video row(s) to Supabase.")

    total_views = sum(r["video_views"] for r in rows)
    total_likes = sum(r["likes"] for r in rows)
    print(f"\nReal totals across all backfilled videos: {total_views:,} views, {total_likes:,} likes.")


if __name__ == "__main__":
    main()
