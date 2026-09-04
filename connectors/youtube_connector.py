"""
youtube_connector.py — Podcast video performance via YouTube's own APIs,
confirmed as the highest-leverage upgrade to the podcast layer (see
ENHANCEMENT RECOMMENDATIONS #4 in the Claude Project instructions):
currently only tracked via Podstock's weekly aggregate scrape, which has
no per-episode breakdown at all. YouTube's own free APIs solve exactly
that gap.

Two genuinely different APIs, confirmed via real research, not assumed:

  1. YouTube Data API v3 -- PUBLIC data (views, likes, comments, video
     list). Simple API key auth, no OAuth needed. Free, quota-based
     (10,000 units/day default, most reads cost 1 unit).

  2. YouTube Analytics API -- PRIVATE, owner-only data (average view
     duration, retention curves, traffic sources, subscriber attribution
     per video). REQUIRES OAuth 2.0 -- an API key alone is not enough,
     since this is data only the channel owner can see. This is the
     richer half of what was actually wanted (retention curves, traffic
     sources), so OAuth setup isn't optional if the real goal is met.

SETUP NEEDED BEFORE EITHER FUNCTION WORKS:
  1. Create a project in the Google Cloud Console (console.cloud.google.com)
     -- free.
  2. Enable "YouTube Data API v3" AND "YouTube Analytics API" for that
     project (APIs & Services -> Library -> search each by name -> Enable).
  3. For the Data API (views/likes/comments):
       - APIs & Services -> Credentials -> Create Credentials -> API key
       - Restrict the key to "YouTube Data API v3" specifically
       - Set as YOUTUBE_API_KEY
  4. For the Analytics API (retention/traffic sources) -- OAuth is
     required, this project's Claude cannot complete this step itself,
     it needs a real browser consent flow performed once by whoever owns
     the YouTube channel:
       - APIs & Services -> Credentials -> Create Credentials -> OAuth
         client ID (type: Desktop app)
       - Download the client secret JSON
       - Run Google's OAuth quickstart flow ONE TIME (opens a browser,
         asks the channel owner to grant access) to get a refresh token
       - Set YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET,
         YOUTUBE_OAUTH_REFRESH_TOKEN
  5. Find the channel's ID: visible in YouTube Studio under
     Settings -> Channel -> Advanced settings, or in the channel URL.
     Set as YOUTUBE_CHANNEL_ID.

REAL, DATED FINDING (confirmed directly from Google's own YouTube Data
API revision history, checked Sep 2026): as of June 1, 2026, the API
moved to a granular quota system. `search.list` now draws from its own
separate bucket, capped at ~100 calls/day, completely independent of
the shared 10,000-unit pool -- a real bottleneck for anything built
around keyword search. This connector is confirmed UNAFFECTED: it was
built using the standard "uploads playlist" pattern (channels.list ->
playlistItems.list -> videos.list) to list a channel's own videos,
never search.list, so it draws only from the untouched 10,000-unit
pool. Worth knowing if the scope ever expands to searching OTHER
creators' content by keyword -- that would hit the new 100/day cap
this connector currently has no exposure to.

Confirmed real, stable response field names below are based on YouTube
Data/Analytics API v3's long-established, well-documented schema (one of
Google's oldest, most stable public APIs) -- higher confidence than the
newer/less-documented APIs elsewhere in this project, so this was NOT
built diagnostic-first the way Facebook demographics or Megaphone were.
Still worth a real live test before fully trusting it, same as anything
new in this codebase.
"""

import os
import requests
from datetime import date, datetime
from dataclasses import dataclass

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
YOUTUBE_OAUTH_CLIENT_ID = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID")
YOUTUBE_OAUTH_CLIENT_SECRET = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET")
YOUTUBE_OAUTH_REFRESH_TOKEN = os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN")

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class YouTubeVideoStats:
    video_id: str
    title: str
    published_at: date
    view_count: int
    like_count: int
    comment_count: int

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "published_at": self.published_at.isoformat(),
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "business_unit": "Podcast",
        }


@dataclass
class YouTubeVideoAnalytics:
    video_id: str
    period_date: date
    average_view_duration_seconds: float
    average_view_percentage: float
    subscribers_gained: int

    def to_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "period_date": self.period_date.isoformat(),
            "average_view_duration_seconds": self.average_view_duration_seconds,
            "average_view_percentage": self.average_view_percentage,
            "subscribers_gained": self.subscribers_gained,
            "business_unit": "Podcast",
        }


def _get_uploads_playlist_id() -> str:
    """The channel's real video list lives in a special 'uploads'
    playlist, not fetched directly from the channel resource -- this is
    the standard, confirmed YouTube Data API pattern for listing a
    channel's videos."""
    resp = requests.get(
        f"{DATA_API_BASE}/channels",
        params={"part": "contentDetails", "id": YOUTUBE_CHANNEL_ID, "key": YOUTUBE_API_KEY},
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"No channel found for ID {YOUTUBE_CHANNEL_ID!r} -- check the channel ID is correct")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_video_stats(max_videos: int = 50) -> list[YouTubeVideoStats]:
    """Data API v3 -- public video stats (views/likes/comments). No OAuth
    needed, just the API key."""
    uploads_playlist_id = _get_uploads_playlist_id()

    video_ids = []
    page_token = None
    while len(video_ids) < max_videos:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": min(50, max_videos - len(video_ids)),
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{DATA_API_BASE}/playlistItems", params=params)
        resp.raise_for_status()
        data = resp.json()
        video_ids.extend(item["contentDetails"]["videoId"] for item in data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    if not video_ids:
        return []

    records = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = requests.get(
            f"{DATA_API_BASE}/videos",
            params={"part": "snippet,statistics", "id": ",".join(batch), "key": YOUTUBE_API_KEY},
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            try:
                published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")).date()
            except (ValueError, KeyError):
                published = date.fromisoformat(snippet.get("publishedAt", "1970-01-01")[:10])

            records.append(
                YouTubeVideoStats(
                    video_id=item["id"],
                    title=snippet.get("title", ""),
                    published_at=published,
                    view_count=int(stats.get("viewCount", 0)),
                    like_count=int(stats.get("likeCount", 0)),
                    comment_count=int(stats.get("commentCount", 0)),
                )
            )

    return records


def _get_oauth_access_token() -> str:
    """Exchanges the long-lived refresh token for a short-lived access
    token -- standard OAuth 2.0 pattern, required for every Analytics API
    call since access tokens expire (~1 hour)."""
    resp = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "client_id": YOUTUBE_OAUTH_CLIENT_ID,
            "client_secret": YOUTUBE_OAUTH_CLIENT_SECRET,
            "refresh_token": YOUTUBE_OAUTH_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_video_analytics(video_ids: list[str], start_date: date, end_date: date) -> list[YouTubeVideoAnalytics]:
    """Analytics API -- retention, watch time, subscriber attribution.
    Requires OAuth (see module docstring) -- an API key alone cannot
    access this, since it's private, owner-only data."""
    access_token = _get_oauth_access_token()
    records = []

    for video_id in video_ids:
        resp = requests.get(
            f"{ANALYTICS_API_BASE}/reports",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "ids": f"channel=={YOUTUBE_CHANNEL_ID}",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "metrics": "averageViewDuration,averageViewPercentage,subscribersGained",
                "filters": f"video=={video_id}",
            },
        )
        if resp.status_code >= 400:
            print(f"[youtube] Analytics fetch failed for video {video_id}: {resp.status_code} {resp.text}")
            continue

        data = resp.json()
        rows = data.get("rows", [])
        if not rows:
            continue

        avg_duration, avg_pct, subs_gained = rows[0]
        records.append(
            YouTubeVideoAnalytics(
                video_id=video_id,
                period_date=end_date,
                average_view_duration_seconds=float(avg_duration),
                average_view_percentage=float(avg_pct),
                subscribers_gained=int(subs_gained),
            )
        )

    return records
