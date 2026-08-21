"""
tiktok_connector.py — TikTok Accounts API connector (organic metrics).

Uses the TikTok for Business "Accounts API" (business-api.tiktok.com), NOT
the consumer Display API (which only returns data for the authenticated
user and lacks follower/engagement fields) and NOT the Research API (not
available to businesses/creators).

IMPORTANT: TikTok requires a separate "Accounts API Access Application
Form" for any new app or scope request involving the TikTok Accounts scope,
effective March 20, 2026. Confirm this has been submitted/approved before
expecting this connector to authenticate successfully.

Requires (via env vars, sourced from 1Password at run time):
    TIKTOK_CLIENT_KEY
    TIKTOK_CLIENT_SECRET
    TIKTOK_REFRESH_TOKEN    -- 1-year refresh token from the initial OAuth
                                consent flow (run once, manually)
    TIKTOK_BUSINESS_ID      -- the TikTok Business account ID being tracked

Access tokens are short-lived (24 hours) — this script refreshes one on
every run rather than trying to cache it between scheduled runs.

NOTE: the Accounts API auth header is `Access-Token:`, NOT the more common
`Authorization: Bearer` — easy to get wrong when copying patterns from
other connectors.
"""

import json
import os
import requests
from datetime import date, datetime, timezone

from models import SocialAccount, SocialMetric, SocialPost, SocialPostMetric
from writer import upsert_rows

TIKTOK_CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
TIKTOK_CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
TIKTOK_REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]
TIKTOK_BUSINESS_ID = os.environ["TIKTOK_BUSINESS_ID"]

TIKTOK_BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


def _validate_credentials_not_empty() -> None:
    """
    Same class of bug found earlier with Plaid's PLAID_ENV: GitHub Actions
    creates an env var from ${{ secrets.X }} even if that secret was NEVER
    actually filled in -- it becomes an empty string, not a missing key. A
    plain os.environ["X"] read succeeds either way, so a blank GitHub
    secret produces a confusing downstream TikTok API error ("app_id:
    Missing data for required field") instead of an immediate, obvious
    message pointing at the actual cause.

    DELIBERATELY called from inside run()/refresh_access_token(), NOT at
    module import time: run_all.py imports every connector at the top of
    the file, OUTSIDE its per-connector try/except isolation. Raising this
    at import time would crash the entire daily sync before any connector
    runs -- exactly the isolation bug this project's whole design exists
    to prevent. Checking lazily, only when this connector is actually
    invoked, keeps the failure properly contained to just this connector.
    """
    missing_or_empty = [
        name for name, value in [
            ("TIKTOK_CLIENT_KEY", TIKTOK_CLIENT_KEY),
            ("TIKTOK_CLIENT_SECRET", TIKTOK_CLIENT_SECRET),
            ("TIKTOK_REFRESH_TOKEN", TIKTOK_REFRESH_TOKEN),
            ("TIKTOK_BUSINESS_ID", TIKTOK_BUSINESS_ID),
        ] if not value
    ]
    if missing_or_empty:
        raise RuntimeError(
            f"The following TikTok environment variable(s) are set but EMPTY: "
            f"{missing_or_empty}. This usually means the GitHub Secret exists "
            f"but was never actually given a real value -- go to Settings -> "
            f"Secrets and variables -> Actions, open each one listed above, "
            f"and re-enter the real value (GitHub never shows existing secret "
            f"values, so re-saving is the only way to confirm/fix one that's "
            f"blank)."
        )


def refresh_access_token() -> str:
    """
    CORRECTED after a real CI failure: this connector was calling the
    WRONG ENDPOINT with the WRONG FIELD NAMES, and TikTok's confusing error
    ("app_id: Missing data for required field") looked at first like an
    access-approval problem rather than a code bug.

    Two real, confirmed fixes, verified against multiple independent
    real-world implementations of this exact endpoint (not guessed):
      1. /oauth2/access_token/ is for the INITIAL authorization-code
         exchange. Refreshing an existing refresh_token requires the
         SEPARATE /oauth2/refresh_token/ endpoint -- a different path,
         not just a different grant_type on the same one.
      2. The TikTok Business API uses `app_id` and `secret` as its field
         names -- NOT `client_key`/`client_secret`, which is the naming
         used by TikTok's OTHER, consumer-facing API
         (open.tiktokapis.com). Easy to mix up since both are called
         "TikTok's API" casually, but they're different products with
         different conventions.
    """
    _validate_credentials_not_empty()

    resp = requests.post(
        f"{TIKTOK_BASE_URL}/oauth2/refresh_token/",
        json={
            "app_id": TIKTOK_CLIENT_KEY,
            "secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": TIKTOK_REFRESH_TOKEN,
        },
    )
    resp.raise_for_status()
    payload = resp.json()

    # Bare `payload["data"]["access_token"]` produced an unhelpful
    # KeyError with no context when this ran in CI. TikTok's own error
    # responses put details in a top-level `error` field distinct from
    # `data` -- surface that directly instead
    # of a bare KeyError, so a real approval-status problem is
    # distinguishable from an actual code bug at a glance.
    if "data" not in payload:
        error_info = payload.get("error", payload)
        raise RuntimeError(
            f"TikTok token refresh did not return the expected shape. "
            f"This usually means Accounts API access isn't approved yet, "
            f"or credentials are wrong. Raw response: {error_info}"
        )
    return payload["data"]["access_token"]


def seed_account() -> int:
    account = SocialAccount(
        platform="tiktok", handle="daniaustin", account_id=TIKTOK_BUSINESS_ID, is_core=True
    )
    return upsert_rows("social_accounts", [account.to_row()])


def fetch_profile_metrics(access_token: str) -> list[SocialMetric]:
    """Account-level: follower count, profile views."""
    today = date.today()
    resp = requests.get(
        f"{TIKTOK_BASE_URL}/business/get/",
        headers={"Access-Token": access_token},
        params={"business_id": TIKTOK_BUSINESS_ID, "fields": '["followers_count","profile_views"]'},
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})

    records = []
    if "followers_count" in data:
        records.append(SocialMetric(TIKTOK_BUSINESS_ID, "followers", today, float(data["followers_count"])))
    if "profile_views" in data:
        records.append(SocialMetric(TIKTOK_BUSINESS_ID, "profile_views", today, float(data["profile_views"])))
    return records


def fetch_video_metrics(access_token: str) -> list[SocialMetric]:
    """
    Aggregates video-level metrics (views, likes, comments, shares) into a
    single daily total. NOTE: enrichment fields go null after ~7 days of no
    engagement on a post, and data stops updating 365 days post-publish —
    expect some undercounting on older content.
    """
    today = date.today()
    resp = requests.get(
        f"{TIKTOK_BASE_URL}/business/video/list/",
        headers={"Access-Token": access_token},
        params={
            "business_id": TIKTOK_BUSINESS_ID,
            "fields": '["video_views","likes","comments","shares"]',
        },
    )
    resp.raise_for_status()
    videos = resp.json().get("data", {}).get("videos", [])

    totals = {"views": 0.0, "likes": 0.0, "comments": 0.0, "shares": 0.0}
    for video in videos:
        totals["views"] += float(video.get("video_views") or 0)
        totals["likes"] += float(video.get("likes") or 0)
        totals["comments"] += float(video.get("comments") or 0)
        totals["shares"] += float(video.get("shares") or 0)

    return [
        SocialMetric(TIKTOK_BUSINESS_ID, metric, today, value)
        for metric, value in totals.items()
    ]


# Per-video fields, taken directly from TikTok's official Accounts API
# documentation for /business/video/list/ -- not inferred.
#
# Three of these have NO Instagram/Facebook equivalent and are the reason
# TikTok's per-post data is arguably the richest of the three platforms:
#   full_video_watched_rate : completion rate -- THE dominant TikTok
#                             algorithmic signal (>30% strong, >50% excellent)
#   impression_sources      : where views came from (For You / Following /
#                             profile / search / hashtag). Healthy accounts
#                             see 70-90% For You on their best videos; under
#                             50% means content is stuck in the follower
#                             bubble rather than reaching new audiences.
#   average_time_watched    : actual attention per view
TIKTOK_VIDEO_FIELDS = [
    "item_id", "create_time", "thumbnail_url", "share_url", "embed_url",
    "caption", "video_views", "likes", "comments", "shares", "reach",
    "video_duration", "full_video_watched_rate", "total_time_watched",
    "average_time_watched", "impression_sources", "audience_countries",
]

# Scalar metrics to store per video. impression_sources and
# audience_countries are dimensional (lists/dicts) and are deliberately NOT
# flattened into social_post_metrics -- they'd need their own table, same
# reasoning as social_audience_demographics. Logged when present so the gap
# is visible rather than silent.
TIKTOK_SCALAR_METRICS = [
    "video_views", "likes", "comments", "shares", "reach",
    "full_video_watched_rate", "total_time_watched", "average_time_watched",
    "video_duration",
]


def fetch_tiktok_videos(access_token: str) -> tuple[list[SocialPost], list[SocialPostMetric]]:
    """
    Per-video metrics from the Accounts API.

    CRITICAL TIMING CONSTRAINT, from TikTok's own documentation: the fields
    reach, full_video_watched_rate, total_time_watched, average_time_watched,
    impression_sources and audience_countries become UNAVAILABLE once a video
    has had no views/likes/comments/shares for more than 7 days. TikTok's
    stated recovery is to interact with the video and retry after 24-48h --
    i.e. these metrics must be captured within days of posting or they're
    effectively lost for that video. A weekly sync is cutting it fine; a
    monthly one would systematically lose this data on all but the most
    durable content.

    ALSO: video_views is a COMBINED organic + paid figure per TikTok's docs.
    If DA ever runs TikTok ads, organic can't be isolated from this alone.
    """
    now = datetime.now(timezone.utc)
    resp = requests.get(
        f"{TIKTOK_BASE_URL}/business/video/list/",
        headers={"Access-Token": access_token},
        params={
            "business_id": TIKTOK_BUSINESS_ID,
            "fields": json.dumps(TIKTOK_VIDEO_FIELDS),
        },
    )
    resp.raise_for_status()
    videos = resp.json().get("data", {}).get("videos", [])

    posts, metrics = [], []
    dimensional_seen = False

    for video in videos:
        item_id = video.get("item_id")
        if not item_id:
            continue

        posted_at = None
        create_time = video.get("create_time")
        if create_time:
            try:
                # TikTok returns a unix timestamp for create_time
                posted_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            except (ValueError, TypeError):
                pass

        posts.append(SocialPost(
            account_id=TIKTOK_BUSINESS_ID, post_id=str(item_id), platform="tiktok",
            media_type="VIDEO", caption=video.get("caption"),
            permalink=video.get("share_url"), posted_at=posted_at,
        ))

        for metric in TIKTOK_SCALAR_METRICS:
            value = video.get(metric)
            if value is None:
                continue  # commonly the 7-day inactivity rule, not an error
            try:
                metrics.append(SocialPostMetric(str(item_id), metric, float(value), now))
            except (TypeError, ValueError):
                continue

        if video.get("impression_sources") or video.get("audience_countries"):
            dimensional_seen = True

    if dimensional_seen:
        print("[tiktok] NOTE: impression_sources / audience_countries present in the "
              "response but not stored -- dimensional data needs its own table "
              "(same shape as social_audience_demographics). Not silently dropped.")

    return posts, metrics


def sync_posts() -> int:
    """Per-video sync. Separate entry point from run(), same as Meta's."""
    access_token = refresh_access_token()
    posts, metrics = fetch_tiktok_videos(access_token)

    written = 0
    if posts:
        written += upsert_rows("social_posts", [p.to_row() for p in posts])
    if metrics:
        written += upsert_rows("social_post_metrics", [m.to_row() for m in metrics])
    print(f"[tiktok] {len(posts)} video(s), {len(metrics)} metric(s)")
    return written


def run() -> int:
    seed_account()
    access_token = refresh_access_token()
    records = fetch_profile_metrics(access_token) + fetch_video_metrics(access_token)
    return upsert_rows("social_metrics", [r.to_row() for r in records])


if __name__ == "__main__":
    count = run()
    print(f"TikTok connector: upserted {count} social metrics.")
